"""JSONL audit-trail writers for DESIGN.md §11.6 追根溯源 audit trail.

Two streams:
  A. sentinel_events.jsonl       — one line per consumed LT audit-log entry
  B. sentinel_mode_changes.jsonl — one line per tier transition, with full
                                    causal context (trigger agent, snapshot,
                                    recent violations)
"""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class JsonlAppender:
    """Tiny append-only JSONL writer that flushes after every record."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        self._fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


class SentinelEventLog:
    """Per-event log corresponding to DESIGN.md §11.6 record A."""

    def __init__(self, path: Path) -> None:
        self._writer = JsonlAppender(path)

    def emit(
        self,
        *,
        ts: str | None,
        request_id: str,
        agent_id: str,
        direction: str,
        lt_action: str,
        lt_rule: str,
        lt_risk_score: float,
        lt_mismatches_critical: int,
        lt_mismatches_warning: int,
        violation: bool,
        violation_reasons: tuple[str, ...],
        oer_after: float,
        ewma_oer_after: float,
        cusum_after: float,
        trust_score_after: float,
        current_tier_global: str,
        source_tier_logfile: str,
    ) -> None:
        self._writer.write(
            {
                "ts": ts or _utcnow_iso(),
                "request_id": request_id,
                "agent_id": agent_id,
                "direction": direction,
                "lt_action": lt_action,
                "lt_rule": lt_rule,
                "lt_risk_score": round(lt_risk_score, 4),
                "lt_mismatches_critical": lt_mismatches_critical,
                "lt_mismatches_warning": lt_mismatches_warning,
                "violation": violation,
                "violation_reasons": list(violation_reasons),
                "oer_after": round(oer_after, 4),
                "ewma_oer_after": round(ewma_oer_after, 4),
                "cusum_after": round(cusum_after, 4),
                "trust_score_after": round(trust_score_after, 4),
                "current_tier_global": current_tier_global,
                "source_tier_logfile": source_tier_logfile,
            }
        )

    def close(self) -> None:
        self._writer.close()


class ModeChangeLog:
    """Tier-transition log corresponding to DESIGN.md §11.6 record B.

    Maintains a small ring buffer of the most recent violating request_ids so
    tier-change records can quote concrete evidence (§11.6 last bullet).
    """

    def __init__(self, path: Path, recent_violation_window: int = 10) -> None:
        self._writer = JsonlAppender(path)
        self._recent_violations: deque[str] = deque(maxlen=recent_violation_window)

    def remember_violation(self, request_id: str) -> None:
        if request_id:
            self._recent_violations.append(request_id)

    def emit(
        self,
        *,
        from_tier: str,
        to_tier: str,
        trigger_agent: str,
        trigger_trust_score: float,
        threshold_crossed: str,
        all_agents_trust_snapshot: dict[str, float],
        policy_yaml_applied: str,
        reason_summary: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        record: dict[str, Any] = {
            "ts": _utcnow_iso(),
            "from_tier": from_tier,
            "to_tier": to_tier,
            "trigger_agent": trigger_agent,
            "trigger_trust_score": round(trigger_trust_score, 4),
            "threshold_crossed": threshold_crossed,
            "all_agents_trust_snapshot": all_agents_trust_snapshot,
            "recent_violation_events": list(self._recent_violations),
            "policy_yaml_applied": policy_yaml_applied,
            "reason_summary": reason_summary,
        }
        if extra:
            record.update(extra)
        self._writer.write(record)

    def close(self) -> None:
        self._writer.close()


class TrustHistoryLog:
    """Lightweight per-agent TrustScore time series for visualization."""

    def __init__(self, path: Path) -> None:
        self._writer = JsonlAppender(path)

    def emit(
        self,
        *,
        ts: str | None,
        agent_id: str,
        trust_score: float,
        ewma: float,
        cusum: float,
        tier: str,
    ) -> None:
        self._writer.write(
            {
                "ts": ts or _utcnow_iso(),
                "agent_id": agent_id,
                "trust_score": round(trust_score, 4),
                "ewma": round(ewma, 4),
                "cusum": round(cusum, 4),
                "tier": tier,
            }
        )

    def close(self) -> None:
        self._writer.close()


def replay_events(path: Path) -> Iterable[dict[str, Any]]:
    """Iterator for offline replay (calibration scripts and ARL₀ analysis)."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
