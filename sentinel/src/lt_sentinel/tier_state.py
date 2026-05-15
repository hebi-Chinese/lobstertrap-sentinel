"""Global tier state — decides which LT instance Sentinel is forwarding to.

Per DESIGN.md §11.2:
    - Trust       : all agents' TrustScore > τ_high
    - Observe     : some agent's TrustScore ∈ [τ_low, τ_high]
    - Lockdown    : some agent's TrustScore < τ_low

The transition is monotonic from worst-case (per-agent minimum):
    - min_trust < τ_low                  → LOCKDOWN
    - τ_low ≤ min_trust < τ_high         → OBSERVE
    - min_trust ≥ τ_high                 → TRUST
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import TIER_LOCKDOWN, TIER_OBSERVE, TIER_TRUST, SPCParams


@dataclass(frozen=True)
class TierDecision:
    tier: str
    threshold_crossed: str | None  # τ_high, τ_low, or None when no change


def decide_tier(min_trust: float, spc: SPCParams) -> str:
    if min_trust < spc.tau_low:
        return TIER_LOCKDOWN
    if min_trust < spc.tau_high:
        return TIER_OBSERVE
    return TIER_TRUST


def transition_reason(prev: str, new: str, spc: SPCParams) -> str | None:
    """Identify which threshold caused a transition, for audit-trail reasoning."""
    if prev == new:
        return None
    order = {TIER_TRUST: 0, TIER_OBSERVE: 1, TIER_LOCKDOWN: 2}
    if order[new] > order[prev]:
        # Escalation: crossed downward through a τ.
        if new == TIER_OBSERVE:
            return f"τ_high={spc.tau_high}"
        return f"τ_low={spc.tau_low}"
    # De-escalation: crossed upward back through a τ.
    if new == TIER_OBSERVE:
        return f"τ_low={spc.tau_low} (recovery)"
    return f"τ_high={spc.tau_high} (recovery)"
