"""Calibration loop — DESIGN.md §12.2 / §12.3 checklist.

Consumes the JSONL written by `runtime.SentinelRuntime` during a happy-path
baseline run and produces:

    µ_dev  = violations / total_chains                       (§12.2.A)
    σ_dev  = √(µ_dev * (1 - µ_dev) / N)                      (p-chart, Montgomery 2009)
    h      = 4 × σ_dev                                       (§12.1, Hawkins & Olwell 1998)
    k      = 0.5 × σ_dev                                     (§12.1, Page 1954)
    ARL₀   = offline replay false-alarm rate                 (§12.2.D)

The calibration is run AFTER the baseline collection and produces a small
calibration_report.json the demo can quote from.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from lt_sentinel.audit_writers import replay_events
from lt_sentinel.config import SPCParams, default_config
from lt_sentinel.metrics import AgentRegistry, p_chart_sigma
from lt_sentinel.tier_state import decide_tier


def measure_mu_dev(events_path: Path) -> tuple[int, int, float, dict[str, tuple[int, int]]]:
    """Return (n_chains, n_violations, mu_dev, per_agent_counts).

    A chain = one ingress event. Egress events are skipped (informational).
    """
    n_chains = 0
    n_violations = 0
    per_agent: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [seen, viol]

    for event in replay_events(events_path):
        if event.get("direction") != "ingress":
            continue
        agent_id = event.get("agent_id") or "<anon>"
        if agent_id == "<anon>":
            continue
        n_chains += 1
        per_agent[agent_id][0] += 1
        if bool(event.get("violation")):
            n_violations += 1
            per_agent[agent_id][1] += 1

    mu_dev = (n_violations / n_chains) if n_chains > 0 else 0.0
    per_agent_counts = {aid: (cnt[0], cnt[1]) for aid, cnt in per_agent.items()}
    return n_chains, n_violations, mu_dev, per_agent_counts


def offline_arl0(events_path: Path, spc: SPCParams) -> tuple[int, int]:
    """Replay events through fresh metrics with calibrated SPC; count tier swaps.

    ARL₀ ≈ n_baseline_events_between_swaps in a no-attack stream.
    """
    registry = AgentRegistry(spc)
    current_tier = "trust"
    n_baseline_events = 0
    swap_indices: list[int] = []

    for event in replay_events(events_path):
        if event.get("direction") != "ingress":
            continue
        aid = event.get("agent_id") or "<anon>"
        if aid == "<anon>":
            continue
        n_baseline_events += 1
        state = registry.get_or_create(aid)
        state.observe(bool(event.get("violation")))
        _, min_trust = registry.min_trust()
        new_tier = decide_tier(min_trust, spc)
        if new_tier != current_tier:
            swap_indices.append(n_baseline_events)
            current_tier = new_tier

    n_swaps = len(swap_indices)
    return n_baseline_events, n_swaps


def main() -> None:
    parser = argparse.ArgumentParser(description="LT-Sentinel SPC calibration")
    parser.add_argument(
        "--events",
        type=Path,
        default=None,
        help="Path to sentinel_events.jsonl (default: from default_config)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Output JSON report path (default: data/calibration_report.json)",
    )
    parser.add_argument("--lambda-ewma", type=float, default=0.2)
    parser.add_argument("--k-sigma-mult", type=float, default=0.5)
    parser.add_argument("--h-sigma-mult", type=float, default=4.0)
    parser.add_argument("--window-size", type=int, default=30)
    args = parser.parse_args()

    cfg = default_config()
    events_path = args.events or cfg.sentinel_events_path
    report_path = args.report or (cfg.project_root / cfg.data_dir / "calibration_report.json")

    if not events_path.exists():
        raise SystemExit(f"events file not found: {events_path}")

    n_chains, n_violations, mu_dev, per_agent_counts = measure_mu_dev(events_path)
    if n_chains == 0:
        raise SystemExit(f"no ingress events in {events_path}; run happy-path first")

    sigma_dev = p_chart_sigma(mu_dev, args.window_size)
    h_concrete = args.h_sigma_mult * sigma_dev
    k_concrete = args.k_sigma_mult * sigma_dev

    sanity = "ok"
    if mu_dev > 0.15:
        sanity = "WARN µ_dev > 0.15 — happy-path may contain attacks or judge is too loose"
    elif mu_dev < 0.01:
        sanity = "WARN µ_dev < 0.01 — judge may be too strict or sample too clean"

    # ARL₀ replay using fresh calibrated parameters.
    calibrated_spc = SPCParams(
        lambda_ewma=args.lambda_ewma,
        k_cusum_sigma_mult=args.k_sigma_mult,
        h_cusum_sigma_mult=args.h_sigma_mult,
        window_size=args.window_size,
        mu_dev=mu_dev,
        sigma_dev=sigma_dev,
    )
    arl_n_events, arl_n_swaps = offline_arl0(events_path, calibrated_spc)
    arl0 = float(arl_n_events) / arl_n_swaps if arl_n_swaps > 0 else math.inf
    arl_target_band = (50, 200)
    arl0_status: str
    if arl_n_swaps == 0:
        arl0_status = "no swaps in baseline (ARL₀ → ∞; OK so long as attack scenarios still trigger)"
    elif arl_target_band[0] <= arl0 <= arl_target_band[1]:
        arl0_status = "ok"
    elif arl0 < arl_target_band[0]:
        arl0_status = "WARN ARL₀ too low — false-alarm rate too high; raise λ or h"
    else:
        arl0_status = "WARN ARL₀ too high — detector too dull; lower λ or h"

    report = {
        "source": str(events_path),
        "n_chains": n_chains,
        "n_violations": n_violations,
        "mu_dev": round(mu_dev, 6),
        "sigma_dev": round(sigma_dev, 6),
        "spc_params": {
            "lambda_ewma": args.lambda_ewma,
            "k_sigma_mult": args.k_sigma_mult,
            "h_sigma_mult": args.h_sigma_mult,
            "window_size": args.window_size,
        },
        "concrete": {
            "k": round(k_concrete, 6),
            "h": round(h_concrete, 6),
            "mu_plus_2sigma": round(mu_dev + 2 * sigma_dev, 6),
            "mu_plus_3sigma": round(mu_dev + 3 * sigma_dev, 6),
        },
        "sanity_check": sanity,
        "arl0": {
            "target_band": arl_target_band,
            "n_baseline_events": arl_n_events,
            "n_swaps": arl_n_swaps,
            "arl0": (None if not math.isfinite(arl0) else round(arl0, 2)),
            "status": arl0_status,
        },
        "per_agent_baseline_counts": {
            aid: {"seen": seen, "violations": viol, "rate": round(viol / seen if seen else 0.0, 4)}
            for aid, (seen, viol) in per_agent_counts.items()
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
