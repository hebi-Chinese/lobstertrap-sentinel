"""The wired-up runtime: supervisor + proxy + tail + metrics + audit writers.

This is what `lt-sentinel run` invokes. Two coroutines run concurrently:

    1. proxy task  — handles incoming agent requests, forwarding to current tier
    2. monitor task — tails LT audit logs, updates per-agent metrics, swaps tier
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audit_writers import ModeChangeLog, SentinelEventLog, TrustHistoryLog, replay_events
from .config import SentinelConfig, TIER_TRUST
from .log_tail import AuditRecord, MultiFileTail
from .metrics import AgentRegistry
from .proxy import TierAwareProxy
from .supervisor import LTSupervisor
from .tier_state import decide_tier, transition_reason
from .violation import judge

logger = logging.getLogger(__name__)


def _parse_event_ts(value: Any) -> float | None:
    """Parse `sentinel_events.jsonl` `ts` (ISO 8601 with optional trailing Z)
    into wall-clock seconds. Returns None on any parse failure — callers
    treat that as "skip idle-decay for this event".
    """
    if not value:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # `fromisoformat` on 3.11+ accepts the trailing Z directly; we normalise
    # for safety on earlier versions and against pre-existing edge cases.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


@dataclass
class _AtomicTierPort:
    """Thread-safe pointer holding the upstream port for the current tier."""

    port: int
    tier: str = TIER_TRUST
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get_port(self) -> int:
        with self._lock:
            return self.port

    def set(self, tier: str, port: int) -> None:
        with self._lock:
            self.tier = tier
            self.port = port


class SentinelRuntime:
    def __init__(self, config: SentinelConfig) -> None:
        self.config = config
        self.supervisor = LTSupervisor(config=config)
        self.registry = AgentRegistry(spc=config.spc)
        self.events_log = SentinelEventLog(config.sentinel_events_path)
        self.mode_log = ModeChangeLog(config.mode_changes_path)
        self.trust_log = TrustHistoryLog(config.trust_history_path)
        self._tier_pointer: _AtomicTierPort | None = None
        self.proxy: TierAwareProxy | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.supervisor.start_all()

        # DESIGN.md §11.6: rebuild in-memory per-agent state from any prior
        # sentinel_events.jsonl on disk so a crash-restart preserves history.
        replayed = self._replay_in_memory_state()

        initial_tier, initial_port = self._resolve_startup_tier()
        self._tier_pointer = _AtomicTierPort(port=initial_port, tier=initial_tier)
        if replayed > 0:
            logger.info(
                "startup replay: rebuilt %d per-agent events; resuming at tier=%s",
                replayed,
                initial_tier,
            )

        host, _, port = self.config.sentinel_listen.partition(":")
        self.proxy = TierAwareProxy(
            listen_host=host,
            listen_port=int(port),
            get_upstream_port=self._tier_pointer.get_port,
        )
        await self.proxy.start()

        # Seed mode-change log with initial tier so reasoning is replayable.
        snap = self.registry.trust_snapshot()
        reason = (
            "Sentinel started; default tier=trust"
            if not snap
            else f"Sentinel restarted; replayed state → tier={self._tier_pointer.tier}"
        )
        self.mode_log.emit(
            from_tier="<init>",
            to_tier=self._tier_pointer.tier,
            trigger_agent="<init>",
            trigger_trust_score=1.0,
            threshold_crossed="<init>",
            all_agents_trust_snapshot=snap,
            policy_yaml_applied=f"policy_{self._tier_pointer.tier}.yaml",
            reason_summary=reason,
        )

    async def run_forever(self) -> None:
        monitor_task = asyncio.create_task(self._monitor_loop(), name="monitor")
        stop_waiter = asyncio.create_task(self._stop.wait(), name="stop-waiter")
        try:
            await asyncio.wait(
                {monitor_task, stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            monitor_task.cancel()
            stop_waiter.cancel()
            for t in (monitor_task, stop_waiter):
                with suppress(asyncio.CancelledError, Exception):
                    await t

    def request_stop(self) -> None:
        self._stop.set()

    # ---- startup replay (DESIGN.md §11.6 last bullet) -----------------------

    def _replay_in_memory_state(self) -> int:
        """Rebuild AgentRegistry state from `sentinel_events.jsonl`.

        Each event's `ts` field is parsed into wall-clock seconds and
        passed into `observe(now=…)` so idle-decay between events applies
        as it would have in real time. Side effect: after replay,
        `last_event_ts` equals the timestamp of the most recent event, so
        the first live event after restart sees `now − last_event_ts`
        worth of idle decay — i.e. any wall-clock gap during which the
        process was down counts toward recovery automatically.
        """
        events_path = self.config.sentinel_events_path
        if not events_path.exists() or events_path.stat().st_size == 0:
            return 0
        n = 0
        for entry in replay_events(events_path):
            if entry.get("direction") != "ingress":
                continue
            agent_id = entry.get("agent_id") or ""
            if not agent_id or agent_id == "<anon>":
                continue
            state = self.registry.get_or_create(agent_id)
            ts = _parse_event_ts(entry.get("ts"))
            state.observe(bool(entry.get("violation")), now=ts)
            n += 1
        return n

    def _resolve_startup_tier(self) -> tuple[str, int]:
        """After replay, pick the tier matching the worst-case TrustScore."""
        if not self.registry.trust_snapshot():
            return TIER_TRUST, self.supervisor.port_for(TIER_TRUST)
        _, min_trust = self.registry.min_trust()
        tier = decide_tier(min_trust, self.config.spc)
        return tier, self.supervisor.port_for(tier)

    async def stop(self) -> None:
        self.request_stop()
        if self.proxy is not None:
            await self.proxy.stop()
        await self.supervisor.stop_all()
        self.events_log.close()
        self.mode_log.close()
        self.trust_log.close()

    # ---- monitor loop ------------------------------------------------------

    async def _monitor_loop(self) -> None:
        tail = MultiFileTail(
            files={
                tier: binding.audit_log_path
                for tier, binding in self.config.tier_bindings.items()
            }
        )
        async for record in tail.stream():
            try:
                self._handle_record(record)
            except Exception:
                logger.exception("error handling audit record: %s", record)

    def _handle_record(self, record: AuditRecord) -> None:
        assert self._tier_pointer is not None
        entry = record.raw

        # Wall-clock pulse for idle-decay across ALL agents — any incoming
        # event also advances time for dormant agents so they recover toward
        # baseline without needing their own traffic. Decay knob lives in
        # SPCParams.idle_decay_half_life_s (set to 0 to disable).
        now = time.time()
        self.registry.apply_idle_decay_all(now)

        agent_id = (entry.get("agent_id") or "<anon>").strip() or "<anon>"
        if agent_id == "<anon>":
            # Anonymous traffic isn't part of the multi-agent governance story;
            # we still count it in event log but exclude from per-identity OER.
            self._emit_event(entry, record, registry_state=None, violation_v=None)
            return

        verdict = judge(entry)
        state = self.registry.get_or_create(agent_id)
        # Decay was already applied via apply_idle_decay_all above; passing
        # `now` here just keeps last_event_ts in sync for this state.
        state.observe(verdict.violation, now=now)

        if verdict.violation:
            self.mode_log.remember_violation(str(entry.get("request_id") or ""))

        # Tier decision is based on global worst-case TrustScore.
        _, min_trust = self.registry.min_trust()
        new_tier = decide_tier(min_trust, self.config.spc)
        if new_tier != self._tier_pointer.tier:
            self._switch_tier(
                new_tier=new_tier,
                trigger_agent=agent_id,
                trigger_trust=state.trust_score,
            )

        self._emit_event(entry, record, registry_state=state, violation_v=verdict)
        self.trust_log.emit(
            ts=str(entry.get("timestamp") or ""),
            agent_id=agent_id,
            trust_score=state.trust_score,
            ewma=state.ewma,
            cusum=state.cusum,
            tier=self._tier_pointer.tier,
        )

    def _switch_tier(self, *, new_tier: str, trigger_agent: str, trigger_trust: float) -> None:
        assert self._tier_pointer is not None
        prev_tier = self._tier_pointer.tier
        new_port = self.supervisor.port_for(new_tier)
        threshold = transition_reason(prev_tier, new_tier, self.config.spc) or "<unknown>"

        self._tier_pointer.set(tier=new_tier, port=new_port)
        logger.info(
            "tier swap %s → %s (triggered by %s, trust=%.3f, port=:%d)",
            prev_tier,
            new_tier,
            trigger_agent,
            trigger_trust,
            new_port,
        )

        self.mode_log.emit(
            from_tier=prev_tier,
            to_tier=new_tier,
            trigger_agent=trigger_agent,
            trigger_trust_score=trigger_trust,
            threshold_crossed=threshold,
            all_agents_trust_snapshot=self.registry.trust_snapshot(),
            policy_yaml_applied=f"policy_{new_tier}.yaml",
            reason_summary=(
                f"{trigger_agent} TrustScore={trigger_trust:.3f} "
                f"crossed {threshold}; transitioning {prev_tier} → {new_tier}"
            ),
        )

    def _emit_event(
        self,
        entry: dict[str, Any],
        record: AuditRecord,
        *,
        registry_state,
        violation_v,
    ) -> None:
        assert self._tier_pointer is not None

        metadata = entry.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        mismatches = entry.get("mismatches") or []

        def _count_severity(level: str) -> int:
            return sum(
                1
                for m in mismatches
                if isinstance(m, dict) and str(m.get("severity", "")).lower() == level
            )

        snap = registry_state.snapshot() if registry_state is not None else {
            "oer": 0.0,
            "ewma": 0.0,
            "cusum": 0.0,
            "trust_score": 1.0,
        }

        self.events_log.emit(
            ts=str(entry.get("timestamp") or ""),
            request_id=str(entry.get("request_id") or ""),
            agent_id=str(entry.get("agent_id") or "<anon>"),
            direction=str(entry.get("direction") or ""),
            lt_action=str(entry.get("action") or ""),
            lt_rule=str(entry.get("rule_name") or ""),
            lt_risk_score=float(metadata.get("risk_score") or 0.0),
            lt_mismatches_critical=_count_severity("critical"),
            lt_mismatches_warning=_count_severity("warning"),
            violation=bool(violation_v.violation) if violation_v else False,
            violation_reasons=tuple(violation_v.reasons) if violation_v else (),
            oer_after=snap["oer"],
            ewma_oer_after=snap["ewma"],
            cusum_after=snap["cusum"],
            trust_score_after=snap["trust_score"],
            current_tier_global=self._tier_pointer.tier,
            source_tier_logfile=record.source,
        )
