"""Time-series visualization for the demo run (DESIGN.md §11.7).

Reads `trust_history.jsonl` (per-agent TrustScore points) and
`sentinel_mode_changes.jsonl` (tier transitions) and emits a single PNG with:

  - one line per agent (TrustScore trajectory)
  - horizontal bands shaded for the three tier regions (trust / observe / lockdown)
  - vertical lines at every tier transition, annotated with trigger_agent
  - title bar showing global current tier sequence

The PNG is suitable for inclusion in the video frame and slide deck.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter
except ImportError:  # pragma: no cover
    raise SystemExit(
        "matplotlib is required; install via:\n"
        "    py -m pip install -e .[viz]"
    )

from datetime import datetime, timezone

from lt_sentinel.config import default_config


_AGENT_COLOR = {
    "router": "#1f77b4",
    "hr_agent": "#d62728",
    "finance_agent": "#2ca02c",
    "it_agent": "#9467bd",
}


def _parse_ts(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def render(*, trust_history: Path, mode_changes: Path, output: Path, tau_high: float, tau_low: float) -> None:
    history = _read_jsonl(trust_history)
    transitions = _read_jsonl(mode_changes)

    if not history:
        raise SystemExit(f"no trust history found at {trust_history} — run sentinel first")

    by_agent: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for row in history:
        if "agent_id" not in row or row["agent_id"] == "<anon>":
            continue
        ts = _parse_ts(row.get("ts", ""))
        score = float(row.get("trust_score", 1.0))
        by_agent[row["agent_id"]].append((ts, score))

    fig, ax = plt.subplots(figsize=(13, 6.5), dpi=120)

    # Tier bands (trust = top, observe = middle, lockdown = bottom).
    ax.axhspan(tau_high, 1.0, color="#d6f5d6", alpha=0.55, zorder=0, label="Trust band")
    ax.axhspan(tau_low, tau_high, color="#fff2cc", alpha=0.55, zorder=0, label="Observe band")
    ax.axhspan(0.0, tau_low, color="#fde0e0", alpha=0.55, zorder=0, label="Lockdown band")

    # Per-agent TrustScore lines.
    for agent, samples in by_agent.items():
        samples.sort(key=lambda x: x[0])
        xs = [s[0] for s in samples]
        ys = [s[1] for s in samples]
        ax.plot(
            xs,
            ys,
            "-",
            label=agent,
            color=_AGENT_COLOR.get(agent, None),
            linewidth=2.0,
            marker="o",
            markersize=3.5,
            zorder=3,
        )

    # Tier transition markers.
    for tr in transitions:
        if tr.get("from_tier", "") in {"<init>", ""}:
            continue
        ts = _parse_ts(tr.get("ts", ""))
        from_t = tr.get("from_tier", "")
        to_t = tr.get("to_tier", "")
        trigger = tr.get("trigger_agent", "")
        ax.axvline(ts, color="#444", linestyle="--", linewidth=1.0, alpha=0.85, zorder=2)
        ax.annotate(
            f"{from_t} → {to_t}\nby {trigger}",
            xy=(ts, 0.96),
            xytext=(6, -2),
            textcoords="offset points",
            fontsize=8,
            color="#222",
            backgroundcolor="white",
            zorder=4,
        )

    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("per-agent TrustScore")
    ax.xaxis.set_major_formatter(DateFormatter("%H:%M:%S"))
    ax.set_title(
        "LT-Sentinel — per-agent TrustScore over time\n"
        "(bands: green=Trust  yellow=Observe  red=Lockdown ; dashed lines = global tier transitions)"
    )
    ax.grid(True, linestyle=":", alpha=0.4, zorder=1)
    ax.legend(loc="lower left", ncol=4, framealpha=0.9, fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    plt.close(fig)
    print(f"wrote {output}")


def main() -> None:
    cfg = default_config()
    parser = argparse.ArgumentParser(description="Render TrustScore time-series chart")
    parser.add_argument("--trust-history", type=Path, default=cfg.trust_history_path)
    parser.add_argument("--mode-changes", type=Path, default=cfg.mode_changes_path)
    parser.add_argument(
        "--output",
        type=Path,
        default=cfg.project_root / cfg.data_dir / "trust_timeseries.png",
    )
    parser.add_argument("--tau-high", type=float, default=cfg.spc.tau_high)
    parser.add_argument("--tau-low", type=float, default=cfg.spc.tau_low)
    args = parser.parse_args()

    render(
        trust_history=args.trust_history,
        mode_changes=args.mode_changes,
        output=args.output,
        tau_high=args.tau_high,
        tau_low=args.tau_low,
    )


if __name__ == "__main__":
    main()
