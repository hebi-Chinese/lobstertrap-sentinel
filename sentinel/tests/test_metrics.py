"""Unit tests pinning the SPC math (DESIGN.md §12) to expected behaviour.

These tests are the regression net for the literature-anchored constants —
if the formulas drift, the demo story stops being defensible.
"""

from __future__ import annotations

import math

import pytest

from lt_sentinel.config import SPCParams
from lt_sentinel.metrics import AgentRegistry, PerAgentState, p_chart_sigma
from lt_sentinel.tier_state import decide_tier
from lt_sentinel.violation import judge


# ---- helpers ---------------------------------------------------------------


def _spc(
    mu: float = 0.075,
    sigma: float = 0.048,
    lam: float = 0.2,
) -> SPCParams:
    """Test helper — pins λ explicitly so unit tests stay decoupled from any
    future runtime tuning of `SPCParams.lambda_ewma`. The math under test
    (EWMA decay, CUSUM increment, TrustScore mapping) is the same regardless;
    we just need a known λ to compute expected values.
    """
    return SPCParams(mu_dev=mu, sigma_dev=sigma, lambda_ewma=lam)


# ---- EWMA ------------------------------------------------------------------


def test_ewma_seeded_at_mu_dev() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    assert s.ewma == pytest.approx(0.10)


def test_ewma_single_zero_observation_decays_toward_zero() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    s.observe(False)
    # EWMA_1 = 0.2*0 + 0.8*0.10 = 0.08
    assert s.ewma == pytest.approx(0.08)


def test_ewma_single_one_observation_jumps_up() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    s.observe(True)
    # EWMA_1 = 0.2*1 + 0.8*0.10 = 0.28
    assert s.ewma == pytest.approx(0.28)


def test_ewma_long_run_of_zeros_settles_near_zero() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    for _ in range(100):
        s.observe(False)
    # 0.8^100 * 0.10 ≈ 2e-11
    assert s.ewma < 1e-6


def test_ewma_long_run_of_ones_settles_near_one() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    for _ in range(100):
        s.observe(True)
    # geometric: limit is 1, reached fast.
    assert s.ewma == pytest.approx(1.0, abs=1e-6)


# ---- CUSUM -----------------------------------------------------------------


def test_cusum_stays_zero_on_clean_traffic() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    for _ in range(50):
        s.observe(False)
    # Increment = (0 - 0.1) - 0.5*0.05 = -0.125 each step; max(0, ...) stays at 0.
    assert s.cusum == 0.0


def test_cusum_accumulates_on_violations() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    for _ in range(5):
        s.observe(True)
    # Each step adds (1 - 0.1) - 0.025 = 0.875.
    assert s.cusum == pytest.approx(5 * 0.875)


def test_cusum_breaches_at_h_4sigma() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    # h = 4σ = 0.2; one violation already pushes CUSUM to 0.875 > 0.2.
    s.observe(True)
    assert s.cusum_breached is True


def test_cusum_resets_on_negative_drift() -> None:
    spc = _spc(mu=0.30, sigma=0.05)  # high baseline
    s = PerAgentState(agent_id="t", spc=spc)
    # First push it up then run zeros until it floors at 0.
    s.observe(True)
    assert s.cusum > 0
    for _ in range(50):
        s.observe(False)
    assert s.cusum == 0.0


# ---- TrustScore (DESIGN.md §12.2.B) ----------------------------------------


def test_trustscore_equals_one_when_ewma_at_mu() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    # Out of the gate EWMA = µ.
    assert s.trust_score == pytest.approx(1.0)


def test_trustscore_at_tau_high_when_ewma_at_mu_plus_2sigma() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    s.ewma = 0.10 + 2 * 0.05  # µ + 2σ = 0.20
    # 1 - 2σ/3σ = 1 - 2/3 ≈ 0.333 ≈ τ_high
    assert s.trust_score == pytest.approx(1 - 2 / 3, abs=1e-3)


def test_trustscore_zero_when_ewma_at_mu_plus_3sigma() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    s.ewma = 0.10 + 3 * 0.05  # µ + 3σ = 0.25
    assert s.trust_score == pytest.approx(0.0, abs=1e-9)


def test_trustscore_clamped_at_zero() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    s = PerAgentState(agent_id="t", spc=spc)
    s.ewma = 1.0  # extreme
    assert s.trust_score == 0.0


def test_trustscore_clamped_at_one() -> None:
    spc = _spc(mu=0.30, sigma=0.05)  # high baseline
    s = PerAgentState(agent_id="t", spc=spc)
    s.ewma = 0.0  # below baseline → clamps to 1
    assert s.trust_score == 1.0


# ---- p-chart σ formula (Montgomery 2009 §7.2) ------------------------------


def test_p_chart_sigma_matches_formula() -> None:
    # σ = √(µ(1-µ)/N)
    assert p_chart_sigma(0.075, 30) == pytest.approx(math.sqrt(0.075 * 0.925 / 30))


def test_p_chart_sigma_boundaries() -> None:
    assert p_chart_sigma(0.0, 30) == 0.0
    assert p_chart_sigma(1.0, 30) == 0.0
    assert p_chart_sigma(0.5, 0) == 0.0


# ---- AgentRegistry ---------------------------------------------------------


def test_registry_isolates_per_agent_state() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    reg = AgentRegistry(spc)
    a = reg.get_or_create("a")
    b = reg.get_or_create("b")
    for _ in range(3):
        a.observe(True)
    snap = reg.trust_snapshot()
    assert snap["a"] < snap["b"]


def test_registry_min_trust_returns_worst_agent() -> None:
    spc = _spc(mu=0.10, sigma=0.05)
    reg = AgentRegistry(spc)
    reg.get_or_create("good")
    bad = reg.get_or_create("bad")
    bad.observe(True)
    bad.observe(True)
    worst, score = reg.min_trust()
    assert worst == "bad"
    assert score < 1.0


# ---- tier_state ------------------------------------------------------------


def test_decide_tier_thresholds() -> None:
    spc = _spc()
    assert decide_tier(1.0, spc) == "trust"
    assert decide_tier(spc.tau_high + 1e-9, spc) == "trust"
    assert decide_tier(spc.tau_high - 1e-9, spc) == "observe"
    assert decide_tier(spc.tau_low + 1e-9, spc) == "observe"
    assert decide_tier(spc.tau_low - 1e-9, spc) == "lockdown"
    assert decide_tier(0.0, spc) == "lockdown"


# ---- violation judgement (DESIGN.md §11.9) ---------------------------------


def _entry(
    *,
    action: str = "ALLOW",
    risk: float = 0.0,
    mismatches: list[dict] | None = None,
) -> dict:
    return {
        "action": action,
        "metadata": {"risk_score": risk},
        "mismatches": mismatches or [],
    }


def test_judge_clean_traffic_not_a_violation() -> None:
    v = judge(_entry(action="ALLOW", risk=0.05))
    assert v.violation is False
    assert v.reasons == ()


def test_judge_deny_action_is_always_violation() -> None:
    v = judge(_entry(action="DENY", risk=0.05))
    assert v.violation is True
    assert "action=DENY" in v.reasons


def test_judge_high_risk_alone_is_violation() -> None:
    v = judge(_entry(action="ALLOW", risk=0.85))
    assert v.violation is True
    assert any("critical" in r for r in v.reasons)


def test_judge_intent_only_critical_without_risk_is_not_violation() -> None:
    # Pure intent-classifier disagreement on a clearly benign prompt is noise
    # (LT compares declared_intent string against a single-token category;
    # without elevated risk it is not actionable).
    v = judge(
        _entry(
            action="ALLOW",
            risk=0.05,
            mismatches=[{"severity": "critical", "field": "intent"}],
        )
    )
    assert v.violation is False


def test_judge_intent_critical_with_medium_risk_is_violation() -> None:
    v = judge(
        _entry(
            action="ALLOW",
            risk=0.45,
            mismatches=[{"severity": "critical", "field": "intent"}],
        )
    )
    assert v.violation is True
    assert any("intent_critical" in r for r in v.reasons)


def test_judge_structural_critical_alone_is_violation() -> None:
    # Critical mismatch on paths/commands/domains is real — the agent declared
    # nothing but DPI extracted a sensitive target. This stays a violation.
    for field in ("paths", "commands", "domains"):
        v = judge(
            _entry(
                action="ALLOW",
                risk=0.05,
                mismatches=[{"severity": "critical", "field": field}],
            )
        )
        assert v.violation is True, f"expected violation for critical {field}"
        assert any("critical_on_paths_commands_or_domains" in r for r in v.reasons)


def test_judge_medium_risk_plus_warning_is_violation() -> None:
    v = judge(
        _entry(
            action="ALLOW",
            risk=0.45,
            mismatches=[{"severity": "warning", "field": "intent"}],
        )
    )
    assert v.violation is True
    assert any("warning_mismatches" in r for r in v.reasons)


def test_judge_warning_alone_is_not_violation() -> None:
    # Just a warning mismatch with low risk is informational, not a violation.
    v = judge(
        _entry(
            action="ALLOW",
            risk=0.05,
            mismatches=[{"severity": "warning", "field": "intent"}],
        )
    )
    assert v.violation is False


def test_judge_severity_score_bounded() -> None:
    v = judge(
        _entry(
            action="DENY",
            risk=1.0,
            mismatches=[
                {"severity": "critical", "field": "intent"},
                {"severity": "critical", "field": "paths"},
                {"severity": "warning", "field": "domains"},
            ],
        )
    )
    assert 0.0 <= v.severity_score <= 1.0
