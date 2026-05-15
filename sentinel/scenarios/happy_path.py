"""Happy-path baseline runner (DESIGN.md §12.2.A) — real multi-agent edition.

Fires N benign user requests through the LangGraph router. The router
classifies each one and forwards to HR / Finance / IT. Workers answer
directly (no tool call needed for some questions) or call their Chroma
RAG tool. All LLM calls flow through Sentinel → LT with proper agent_id.

After completion, run `calibrate.py` against sentinel_events.jsonl to
compute μ_dev / σ_dev / h_concrete / ARL₀ on real agent traffic.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time

from .graph_runner import GraphRunner
from .prompts import FINANCE_HAPPY, HR_HAPPY, IT_HAPPY, ROUTER_HAPPY


def _build_corpus() -> list[str]:
    return ROUTER_HAPPY + HR_HAPPY + FINANCE_HAPPY + IT_HAPPY


async def run(*, n_chains: int, qps: float, seed: int) -> None:
    rng = random.Random(seed)
    corpus = _build_corpus()
    delay = 1.0 / qps if qps > 0 else 0.0
    runner = GraphRunner()
    start = time.time()

    by_route: dict[str, int] = {}
    n_tool: int = 0
    n_err: int = 0

    for i in range(n_chains):
        text = rng.choice(corpus)
        outcome = await runner.user_turn(text)
        by_route[outcome.routed_to] = by_route.get(outcome.routed_to, 0) + 1
        if outcome.tool_called:
            n_tool += 1
        if outcome.error:
            n_err += 1
        print(f"[{i + 1:3d}/{n_chains}] {outcome.short}")
        if delay > 0:
            await asyncio.sleep(delay)

    elapsed = time.time() - start
    print()
    print(f"happy-path complete: {n_chains} chains in {elapsed:.1f}s "
          f"({n_chains / max(elapsed, 0.001):.2f} chains/s)")
    print(f"router distribution: {by_route}")
    print(f"tool calls          : {n_tool}/{n_chains}")
    print(f"errors              : {n_err}/{n_chains}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LT-Sentinel happy-path baseline runner (LangGraph)")
    parser.add_argument("--n", type=int, default=80, help="number of user chains")
    parser.add_argument("--qps", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=20260515)
    args = parser.parse_args()
    asyncio.run(run(n_chains=args.n, qps=args.qps, seed=args.seed))


if __name__ == "__main__":
    main()
