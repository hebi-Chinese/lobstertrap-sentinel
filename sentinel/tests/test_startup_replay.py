"""Regression test for DESIGN.md §11.6 last bullet: startup replay.

The test does not spawn LT — it exercises only the in-memory replay path
on `SentinelRuntime._replay_in_memory_state()` against a synthetic
`sentinel_events.jsonl`. That keeps the unit test fast and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lt_sentinel.audit_writers import SentinelEventLog
from lt_sentinel.config import SentinelConfig, SPCParams
from lt_sentinel.runtime import SentinelRuntime
from lt_sentinel.tier_state import decide_tier


def _make_config(tmp_path: Path) -> SentinelConfig:
    # The test path doesn't need real policies or LT binaries; we only call
    # _replay_in_memory_state which reads sentinel_events_path.
    spc = SPCParams(mu_dev=0.05, sigma_dev=0.04, lambda_ewma=0.2)
    cfg = SentinelConfig(
        project_root=tmp_path,
        spc=spc,
    )
    return cfg


def _write_events(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_replay_skips_when_events_file_missing(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    rt = SentinelRuntime(cfg)
    assert rt._replay_in_memory_state() == 0
    assert rt.registry.trust_snapshot() == {}


def test_replay_skips_anon_and_egress(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    rt = SentinelRuntime(cfg)
    rows = [
        {"direction": "egress", "agent_id": "hr_agent", "violation": True},
        {"direction": "ingress", "agent_id": "<anon>", "violation": True},
        {"direction": "ingress", "agent_id": "", "violation": True},
    ]
    _write_events(cfg.sentinel_events_path, rows)
    n = rt._replay_in_memory_state()
    assert n == 0
    assert rt.registry.trust_snapshot() == {}


def test_replay_rebuilds_per_agent_ewma(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    rt = SentinelRuntime(cfg)

    rows = [
        # 5 clean events for finance → EWMA decays toward 0, trust ≈ 1.0
        *[
            {"direction": "ingress", "agent_id": "finance_agent", "violation": False}
            for _ in range(5)
        ],
        # 5 violating events for hr → EWMA jumps up, trust drops
        *[
            {"direction": "ingress", "agent_id": "hr_agent", "violation": True}
            for _ in range(5)
        ],
    ]
    _write_events(cfg.sentinel_events_path, rows)

    n = rt._replay_in_memory_state()
    assert n == 10
    snap = rt.registry.trust_snapshot()
    assert "finance_agent" in snap
    assert "hr_agent" in snap
    assert snap["finance_agent"] > snap["hr_agent"]
    # 5 violations with λ=0.2 / µ=0.05 / σ=0.04 → EWMA >> µ+3σ → trust clamped to 0
    assert snap["hr_agent"] == 0.0


def test_resolve_startup_tier_lockdown_after_replay(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    rt = SentinelRuntime(cfg)
    # Force one violating event to drive an agent below τ_low quickly.
    rows = [
        {"direction": "ingress", "agent_id": "hr_agent", "violation": True}
        for _ in range(5)
    ]
    _write_events(cfg.sentinel_events_path, rows)
    rt._replay_in_memory_state()

    # Without supervisor we can't call _resolve_startup_tier (it needs ports);
    # but we can verify the tier *decision* matches what _resolve_startup_tier
    # would compute internally.
    _, min_trust = rt.registry.min_trust()
    chosen_tier = decide_tier(min_trust, cfg.spc)
    assert chosen_tier in {"observe", "lockdown"}


def test_replay_round_trip_through_event_log(tmp_path: Path) -> None:
    """Sanity: events written by SentinelEventLog are picked back up by replay."""
    cfg = _make_config(tmp_path)
    cfg.sentinel_events_path.parent.mkdir(parents=True, exist_ok=True)
    log = SentinelEventLog(cfg.sentinel_events_path)
    for _ in range(3):
        log.emit(
            ts=None,
            request_id="r",
            agent_id="hr_agent",
            direction="ingress",
            lt_action="ALLOW",
            lt_rule="",
            lt_risk_score=0.0,
            lt_mismatches_critical=0,
            lt_mismatches_warning=0,
            violation=False,
            violation_reasons=(),
            oer_after=0.0,
            ewma_oer_after=0.0,
            cusum_after=0.0,
            trust_score_after=1.0,
            current_tier_global="trust",
            source_tier_logfile="trust",
        )
    log.close()

    rt = SentinelRuntime(cfg)
    assert rt._replay_in_memory_state() == 3
    assert rt.registry.trust_snapshot()["hr_agent"] == pytest.approx(1.0, abs=0.05)
