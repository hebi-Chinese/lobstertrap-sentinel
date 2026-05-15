"""CLI entrypoint for LT-Sentinel.

Usage:
    lt-sentinel run            # start supervisor + proxy + monitor (foreground)
    lt-sentinel show-config    # print loaded config + tier bindings
    lt-sentinel replay <file>  # offline replay of an audit-log jsonl
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import click

from .config import default_config
from .runtime import SentinelRuntime


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    _configure_logging(verbose)
    ctx.ensure_object(dict)


@main.command("show-config")
def show_config() -> None:
    cfg = default_config()
    click.echo(f"project_root         : {cfg.project_root}")
    click.echo(f"sentinel_listen      : {cfg.sentinel_listen}")
    click.echo(f"backend_url          : {cfg.backend_url}")
    click.echo(f"lt_binary            : {cfg.project_root / cfg.lt_binary}")
    click.echo(f"sentinel_events_path : {cfg.sentinel_events_path}")
    click.echo(f"mode_changes_path    : {cfg.mode_changes_path}")
    click.echo(f"trust_history_path   : {cfg.trust_history_path}")
    click.echo("tier_bindings:")
    for tier, b in cfg.tier_bindings.items():
        click.echo(
            f"  - {tier:9s} port={b.listen_port}  "
            f"policy={b.policy_yaml.name}  audit={b.audit_log_path.name}"
        )
    click.echo("spc:")
    spc = cfg.spc
    click.echo(
        f"  lambda_ewma={spc.lambda_ewma}  k_mult={spc.k_cusum_sigma_mult}*sigma  "
        f"h_mult={spc.h_cusum_sigma_mult}*sigma  N={spc.window_size}  "
        f"tau_high={spc.tau_high}  tau_low={spc.tau_low}"
    )
    click.echo(
        f"  mu_dev={spc.mu_dev}  sigma_dev={spc.sigma_dev}  k={spc.k_cusum:.4f}  "
        f"h={spc.h_cusum:.4f}"
    )


@main.command("run")
def run_cmd() -> None:
    """Start LT-Sentinel: spawn 3 LT instances, start proxy and monitor."""
    cfg = default_config()
    runtime = SentinelRuntime(cfg)

    async def _go() -> None:
        await runtime.start()
        click.echo(f"\n  LT-Sentinel up on http://{cfg.sentinel_listen}", err=True)
        click.echo(
            f"  Trust   :{cfg.tier_bindings['trust'].listen_port}  "
            f"Observe :{cfg.tier_bindings['observe'].listen_port}  "
            f"Lockdown:{cfg.tier_bindings['lockdown'].listen_port}",
            err=True,
        )
        click.echo(
            f"  Events  → {cfg.sentinel_events_path.relative_to(cfg.project_root)}",
            err=True,
        )
        click.echo(
            f"  Mode    → {cfg.mode_changes_path.relative_to(cfg.project_root)}\n",
            err=True,
        )

        loop = asyncio.get_running_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, runtime.request_stop)

        try:
            await runtime.run_forever()
        finally:
            await runtime.stop()

    try:
        asyncio.run(_go())
    except KeyboardInterrupt:
        # asyncio.run swallows the cancellation; cleanup already ran in finally.
        pass


@main.command("replay")
@click.argument("audit_log", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def replay_cmd(audit_log: Path) -> None:
    """Replay an LT audit-log jsonl offline; print per-event metrics."""
    from .audit_writers import replay_events
    from .metrics import AgentRegistry
    from .tier_state import decide_tier
    from .violation import judge

    cfg = default_config()
    registry = AgentRegistry(cfg.spc)
    n_total = 0
    n_violations = 0
    tier_changes: list[tuple[int, str, str]] = []
    current_tier = "trust"

    for entry in replay_events(audit_log):
        n_total += 1
        agent_id = (entry.get("agent_id") or "<anon>").strip() or "<anon>"
        if agent_id == "<anon>":
            continue
        v = judge(entry)
        state = registry.get_or_create(agent_id)
        state.observe(v.violation)
        if v.violation:
            n_violations += 1
        _, min_trust = registry.min_trust()
        new_tier = decide_tier(min_trust, cfg.spc)
        if new_tier != current_tier:
            tier_changes.append((n_total, current_tier, new_tier))
            current_tier = new_tier

    click.echo(f"replayed {n_total} entries; {n_violations} judged as violations")
    click.echo(f"final tier: {current_tier}")
    click.echo(f"per-agent trust snapshot:")
    for aid, t in registry.trust_snapshot().items():
        click.echo(f"  - {aid:20s}  trust={t:.4f}")
    if tier_changes:
        click.echo("tier transitions:")
        for n, old, new in tier_changes:
            click.echo(f"  - at event #{n}:  {old} → {new}")


if __name__ == "__main__":
    main()
