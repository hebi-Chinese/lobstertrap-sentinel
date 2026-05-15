"""Runtime configuration — all knobs in one place.

Numerical defaults are anchored to DESIGN.md §12.1 (literature constants);
µ_dev / σ_dev are filled in after the happy-path baseline run (see §12.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


# ---- tier constants ---------------------------------------------------------

TIER_TRUST = "trust"
TIER_OBSERVE = "observe"
TIER_LOCKDOWN = "lockdown"
TIERS = (TIER_TRUST, TIER_OBSERVE, TIER_LOCKDOWN)


@dataclass(frozen=True)
class TierBinding:
    """Maps a tier to a backing LT instance (port + audit-log file)."""

    name: str
    listen_port: int
    audit_log_path: Path
    policy_yaml: Path


# ---- SPC / calibration parameters ------------------------------------------


@dataclass(frozen=True)
class SPCParams:
    """Statistical Process Control knobs.

    Defaults from DESIGN.md §12.1 (literature-locked); µ_dev / σ_dev filled
    in by `scripts/calibrate.py` after happy-path baseline run.

    Calibration finding (2026-05-15 N=220 happy-path):
      measured µ_dev = 0.0 — judge correctly rejects LT intent-classifier
      noise. σ formula degenerates at µ=0, so we adopt the low-end Bayesian
      prior from Agent Security Bench (ICLR 2025) of µ_dev = 0.05 instead
      of the raw measurement. The empirical takeaway: judge is conservative
      enough that no false alarms occur on clean traffic (ARL₀ → ∞).
    """

    # λ lowered to 0.05 (Lucas & Saccucci 1990 [0.05, 0.30] range floor) so a
    # binary 0/1 event series ramps EWMA smoothly across the 3 TrustScore
    # tiers (1 violation → still trust; 2 → observe; 3 → lockdown). The
    # high-severity single-event case is independently caught by the judge's
    # action=DENY and risk_score≥0.7 rules.
    lambda_ewma: float = 0.05
    k_cusum_sigma_mult: float = 0.5  # Page 1954 / Hawkins & Olwell 1998
    h_cusum_sigma_mult: float = 4.0  # Hawkins & Olwell 1998
    window_size: int = 30  # Münz & Carle 2008

    # Tier thresholds in TrustScore space (locked per DESIGN.md §12.2.B)
    tau_high: float = 0.33
    tau_low: float = 0.10

    # Bayesian prior µ_dev = 0.05 (Agent Security Bench ICLR 2025 floor of
    # the 0.05–0.10 baseline range). σ from p-chart formula §12.2.A.
    mu_dev: float = 0.05
    sigma_dev: float = 0.040  # ≈ √(0.05 * 0.95 / 30) = 0.0398

    # Wall-clock seconds after which an idle agent's EWMA drifts halfway
    # back to µ_dev. Prevents "dormant agent stuck in lockdown forever"
    # (covered in DESIGN.md §11.2 footnote). Set to 0 to disable.
    # Chosen so the demo's <5-minute event-driven dynamics dominate over
    # idle decay, but a 1-hour dormant agent (~6 half-lives) is effectively
    # reset to baseline. This is an engineering parameter, not literature.
    idle_decay_half_life_s: float = 600.0

    @property
    def k_cusum(self) -> float:
        return self.k_cusum_sigma_mult * self.sigma_dev

    @property
    def h_cusum(self) -> float:
        return self.h_cusum_sigma_mult * self.sigma_dev


# ---- top-level config -------------------------------------------------------


@dataclass(frozen=True)
class SentinelConfig:
    project_root: Path
    sentinel_listen: str = "127.0.0.1:8080"  # what agents talk to
    backend_url: str = "http://localhost:11434"  # Ollama
    lt_binary: Path = field(default_factory=lambda: Path("lobstertrap/lobstertrap.exe"))
    policies_dir: Path = field(default_factory=lambda: Path("sentinel/policies"))
    data_dir: Path = field(default_factory=lambda: Path("sentinel/data"))
    spc: SPCParams = field(default_factory=SPCParams)

    @property
    def tier_bindings(self) -> dict[str, TierBinding]:
        ports = {TIER_TRUST: 18081, TIER_OBSERVE: 18082, TIER_LOCKDOWN: 18083}
        bindings: dict[str, TierBinding] = {}
        for tier in TIERS:
            bindings[tier] = TierBinding(
                name=tier,
                listen_port=ports[tier],
                audit_log_path=self.project_root
                / self.data_dir
                / f"lt_audit_{tier}.jsonl",
                policy_yaml=self.project_root
                / self.policies_dir
                / f"policy_{tier}.yaml",
            )
        return bindings

    @property
    def sentinel_events_path(self) -> Path:
        return self.project_root / self.data_dir / "sentinel_events.jsonl"

    @property
    def mode_changes_path(self) -> Path:
        return self.project_root / self.data_dir / "sentinel_mode_changes.jsonl"

    @property
    def trust_history_path(self) -> Path:
        return self.project_root / self.data_dir / "trust_history.jsonl"


def default_config(project_root: Path | str | None = None) -> SentinelConfig:
    if project_root is None:
        # The sentinel package lives at <root>/sentinel/src/lt_sentinel/.
        project_root = Path(__file__).resolve().parents[3]
    return SentinelConfig(project_root=Path(project_root))
