"""Canonical demo run — all three attack scenarios in one live Sentinel run,
all routed through the real LangGraph multi-agent system.

Expected story arc on the resulting TrustScore chart:

    finance_agent : never targeted by any scenario, stays at ~1.0 (control)
    router        : Scenario A injects through it — saw-tooth descent
    hr_agent      : Scenario B targets it — flat then sharp drop
    it_agent      : Scenario C poisons its tool — gradual ramp into lockdown
"""

from __future__ import annotations

import argparse
import asyncio
import random

from .attack_a_slow_injection import SLOW_INJECTION_TURNS
from .attack_b_trust_then_burst import BURST_PROMPTS
from .attack_c_tool_poisoning import USER_QUESTIONS as TOOL_QUESTIONS
from .graph_runner import GraphRunner
from .poisoned_tool import POISONED_RESPONSES, fetch_external_calendar, reset_poisoned_counter
from .prompts import FINANCE_HAPPY, HR_HAPPY, IT_HAPPY, ROUTER_HAPPY


async def _drive(runner: GraphRunner, label: str, text: str) -> None:
    outcome = await runner.user_turn(text)
    print(f"  [{label:>8s}]  {outcome.short}")


async def run(*, qps: float, seed: int) -> None:
    rng = random.Random(seed)
    delay = 1.0 / qps if qps > 0 else 0.0
    reset_poisoned_counter()

    # Build two graphs: the default one (used for phases 1-4) and the
    # poisoned variant for Phase 5 (Scenario C). They share Chroma so the
    # second build is fast.
    from pathlib import Path
    from lt_agents.graph import build_graph

    chroma_dir = Path(__file__).resolve().parents[1] / "data" / "chroma_seed"
    default_runner = GraphRunner(chroma_dir=chroma_dir)
    poisoned_graph = build_graph(chroma_dir, extra_it_tools=[fetch_external_calendar])
    poisoned_runner = GraphRunner.__new__(GraphRunner)
    poisoned_runner._chroma_dir = chroma_dir  # type: ignore[attr-defined]
    poisoned_runner._graph = poisoned_graph  # type: ignore[attr-defined]

    print("\n=== Phase 1 — happy warm-up across all four entry points ===")
    warm_corpus = [
        ("finance", FINANCE_HAPPY),
        ("router", ROUTER_HAPPY),
        ("hr", HR_HAPPY),
        ("it", IT_HAPPY),
    ]
    plan: list[tuple[str, str]] = []
    for _ in range(2):
        for label, corpus in warm_corpus:
            plan.append((label, rng.choice(corpus)))
    for label, text in plan:
        await _drive(default_runner, f"warm.{label}", text)
        if delay > 0:
            await asyncio.sleep(delay)

    print("\n=== Phase 2 — Scenario A (slow injection) — 2 cycles through router ===")
    for cycle in range(2):
        for text in SLOW_INJECTION_TURNS:
            await _drive(default_runner, f"A.c{cycle + 1}", text)
            if delay > 0:
                await asyncio.sleep(delay)

    print("\n=== Phase 3 — recovery on router (6 benign turns) ===")
    for _ in range(6):
        await _drive(default_runner, "A.rec", rng.choice(ROUTER_HAPPY))
        if delay > 0:
            await asyncio.sleep(delay)

    print("\n=== Phase 4 — Scenario B (trust-then-burst) on hr_agent ===")
    for _ in range(15):
        await _drive(default_runner, "B.warm", rng.choice(HR_HAPPY))
        if delay > 0:
            await asyncio.sleep(delay)
    for i, text in enumerate(BURST_PROMPTS):
        await _drive(default_runner, f"B.brst{i + 1}", text)
        if delay > 0:
            await asyncio.sleep(delay)

    print("\n=== Phase 5 — Scenario C (tool poisoning) on it_agent ===")
    n_turns = min(len(TOOL_QUESTIONS), len(POISONED_RESPONSES))
    for i in range(n_turns):
        await _drive(poisoned_runner, f"C.t{i + 1}", TOOL_QUESTIONS[i])
        if delay > 0:
            await asyncio.sleep(delay)

    print("\nCanonical demo complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="LT-Sentinel canonical demo run (LangGraph edition)")
    parser.add_argument("--qps", type=float, default=2.0)
    parser.add_argument("--seed", type=int, default=20260516)
    args = parser.parse_args()
    asyncio.run(run(qps=args.qps, seed=args.seed))


if __name__ == "__main__":
    main()
