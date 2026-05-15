"""Per-agent SPC state — sliding-window OER, EWMA, CUSUM, TrustScore.

Implements the math from DESIGN.md §12 with explicit citations:
    EWMA   — Lucas & Saccucci 1990 (Technometrics 32:1)
    CUSUM  — Page 1954 (Biometrika 41) + Hawkins & Olwell 1998
    OER    — *The Trust Paradox in LLM-Based Multi-Agent Systems* arxiv:2510.18563

Per-identity state lives in PerAgentState; the registry holds one of those
per agent_id seen in the audit stream.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from .config import SPCParams


@dataclass
class PerAgentState:
    """One agent's running state. Mutable on purpose — updated per event."""

    agent_id: str
    spc: SPCParams

    # Sliding window of recent chain-level binary violations (0/1).
    # Per DESIGN.md §6.2 OER is chain-level, but for the demo we treat each
    # audit-log entry as a chain (one prompt = one chain). This matches the
    # baseline measurement procedure in §12.2.A.
    window: deque[int] = field(default_factory=lambda: deque(maxlen=30))

    # EWMA initialised to µ_dev per §12.1 row 1.
    ewma: float = 0.0

    # CUSUM accumulator, lower-side ignored since OER only inflates upward.
    cusum: float = 0.0

    n_seen: int = 0
    n_violations: int = 0

    def __post_init__(self) -> None:
        # Resize window to spc.window_size and seed EWMA at µ_dev.
        self.window = deque(maxlen=self.spc.window_size)
        self.ewma = self.spc.mu_dev

    # ---- updates -----------------------------------------------------------

    def observe(self, is_violation: bool) -> None:
        """Update the state given a single chain's outcome."""
        x = 1 if is_violation else 0
        self.window.append(x)
        self.n_seen += 1
        if is_violation:
            self.n_violations += 1

        # EWMA: EWMA_t = λ·X_t + (1-λ)·EWMA_{t-1}
        lam = self.spc.lambda_ewma
        self.ewma = lam * x + (1.0 - lam) * self.ewma

        # CUSUM (one-sided upward): S_t = max(0, S_{t-1} + (X_t - µ) - k)
        increment = (x - self.spc.mu_dev) - self.spc.k_cusum
        self.cusum = max(0.0, self.cusum + increment)

    # ---- read-outs ---------------------------------------------------------

    @property
    def oer(self) -> float:
        """Window OER (chain-level violation rate over the last N entries)."""
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)

    @property
    def trust_score(self) -> float:
        """TrustScore from DESIGN.md §12.2.B.

            TrustScore = clamp(1 - (EWMA_OER - µ) / (3σ), 0, 1)

        EWMA=µ → 1.0; EWMA=µ+3σ → 0.0; clamped at both ends.
        """
        three_sigma = 3.0 * self.spc.sigma_dev
        if three_sigma <= 0:
            return 1.0
        raw = 1.0 - (self.ewma - self.spc.mu_dev) / three_sigma
        return max(0.0, min(1.0, raw))

    @property
    def cusum_breached(self) -> bool:
        """CUSUM drift confirmation (DESIGN.md §12.1, h = 4σ)."""
        return self.cusum > self.spc.h_cusum

    def snapshot(self) -> dict[str, float]:
        return {
            "oer": self.oer,
            "ewma": self.ewma,
            "cusum": self.cusum,
            "trust_score": self.trust_score,
            "cusum_breached": float(self.cusum_breached),
            "n_seen": float(self.n_seen),
            "n_violations": float(self.n_violations),
        }


class AgentRegistry:
    """Holds one PerAgentState per agent_id; the entry point for the runtime."""

    def __init__(self, spc: SPCParams) -> None:
        self._spc = spc
        self._states: dict[str, PerAgentState] = {}

    def get_or_create(self, agent_id: str) -> PerAgentState:
        if agent_id not in self._states:
            self._states[agent_id] = PerAgentState(agent_id=agent_id, spc=self._spc)
        return self._states[agent_id]

    def states(self) -> Iterable[PerAgentState]:
        return self._states.values()

    def trust_snapshot(self) -> dict[str, float]:
        return {aid: round(s.trust_score, 4) for aid, s in self._states.items()}

    def min_trust(self) -> tuple[str | None, float]:
        if not self._states:
            return None, 1.0
        worst_id, worst = min(
            self._states.items(),
            key=lambda kv: kv[1].trust_score,
        )
        return worst_id, worst.trust_score


def p_chart_sigma(mu: float, n: int) -> float:
    """σ formula for proportion data (Montgomery 2009 §7.2).

        σ = √(µ(1-µ) / N)
    """
    if n <= 0:
        return 0.0
    if mu <= 0 or mu >= 1:
        return 0.0
    return math.sqrt(mu * (1.0 - mu) / n)
