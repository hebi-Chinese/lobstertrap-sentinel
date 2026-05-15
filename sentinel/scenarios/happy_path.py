"""Happy-path baseline runner (DESIGN.md §12.2.A).

Fires N normal AcmeCorp request chains through Sentinel:8080, one chain per
ScriptedTurn from prompts.py. Each prompt is a routine internal query that
should NOT trigger LT's DPI rules. Run from a fresh Sentinel start so the
sentinel_events.jsonl only contains baseline data.

After completion, run `calibrate.py` against the produced sentinel_events.jsonl
to compute µ_dev, σ_dev, h_concrete, and offline ARL₀.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from pathlib import Path

from .client import SentinelClient
from .prompts import happy_path_corpus


async def _drive_one_turn(client: SentinelClient, turn) -> tuple[str, str, bool]:
    res = await client.send_chat(
        agent_id=turn.agent_id,
        declared_intent=turn.declared_intent,
        user_text=turn.user_text,
    )
    return turn.agent_id, res.verdict, res.rejected


async def run(
    *,
    base_url: str,
    model: str,
    n_chains: int,
    max_tokens: int,
    seed: int,
    qps: float,
) -> None:
    corpus = happy_path_corpus()
    rng = random.Random(seed)
    plan = [rng.choice(corpus) for _ in range(n_chains)]

    n_by_agent: dict[str, int] = {}
    n_rejected_by_agent: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}
    start = time.time()

    delay = 1.0 / qps if qps > 0 else 0.0

    async with SentinelClient(
        base_url=base_url, model=model, max_tokens=max_tokens
    ) as client:
        for i, turn in enumerate(plan):
            try:
                aid, verdict, rejected = await _drive_one_turn(client, turn)
            except Exception as exc:
                print(f"[{i+1:3d}/{n_chains}] {turn.agent_id:14s}  ERROR: {exc}")
                continue
            n_by_agent[aid] = n_by_agent.get(aid, 0) + 1
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
            if rejected:
                n_rejected_by_agent[aid] = n_rejected_by_agent.get(aid, 0) + 1
            print(
                f"[{i+1:3d}/{n_chains}] {turn.agent_id:14s}  verdict={verdict:6s}"
                f"  rej={'Y' if rejected else 'n'}"
            )
            if delay > 0:
                await asyncio.sleep(delay)

    elapsed = time.time() - start
    print()
    print(f"happy-path complete: {n_chains} chains in {elapsed:.1f}s "
          f"({n_chains / max(elapsed, 0.001):.2f} chains/s)")
    print(f"verdict distribution: {verdict_counts}")
    print(f"per-agent counts:    {n_by_agent}")
    print(f"per-agent rejections: {n_rejected_by_agent}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LT-Sentinel happy-path baseline runner")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--n", type=int, default=200, help="number of chains")
    parser.add_argument("--max-tokens", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260515)
    parser.add_argument("--qps", type=float, default=4.0, help="target requests/s (sequential, not concurrent)")
    args = parser.parse_args()

    asyncio.run(
        run(
            base_url=args.base_url,
            model=args.model,
            n_chains=args.n,
            max_tokens=args.max_tokens,
            seed=args.seed,
            qps=args.qps,
        )
    )


if __name__ == "__main__":
    main()
