"""Canonical demo run — runs all three attack scenarios end-to-end against a
single live Sentinel instance, producing the dataset used in the video and
the slide deck.

Expected story arc on the resulting TrustScore chart:

    finance_agent : stays at 1.0 throughout (control — never attacked)
    router        : Scenario A (slow injection) — gradual oscillating descent
    hr_agent      : Scenario B (trust-then-burst) — flat then sharp drop
    it_agent      : Scenario C (tool poisoning) — gradual ramp with each turn

Sentinel must already be running on :8080. Use a fresh Sentinel start so
trust_history.jsonl / sentinel_events.jsonl are empty.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time

from .attack_a_slow_injection import SLOW_INJECTION_TURNS
from .attack_b_trust_then_burst import BURST_PROMPTS
from .attack_c_tool_poisoning import POISONED_TOOL_TURNS
from .client import SentinelClient
from .prompts import HR_HAPPY, IT_HAPPY, ROUTER_HAPPY, FINANCE_HAPPY


async def _drive(client: SentinelClient, *, agent_id: str, text: str, label: str) -> None:
    try:
        res = await client.send_chat(
            agent_id=agent_id,
            declared_intent="general",
            user_text=text,
        )
    except Exception as exc:
        print(f"  [{label}] {agent_id:14s}  ERROR: {exc}")
        return
    print(
        f"  [{label}] {agent_id:14s}  verdict={res.verdict:6s}  "
        f"rule={res.rule_name or '-':28s}  text={text[:60]!r}"
    )


async def run(*, base_url: str, model: str, qps: float, seed: int) -> None:
    rng = random.Random(seed)
    delay = 1.0 / qps if qps > 0 else 0.0

    async with SentinelClient(base_url=base_url, model=model, max_tokens=6) as client:

        print("\n=== Phase 1 — happy warm-up across all agents (30 chains) ===")
        warm = []
        for _ in range(8):
            warm.append(("finance_agent", rng.choice(FINANCE_HAPPY)))
            warm.append(("router", rng.choice(ROUTER_HAPPY)))
            warm.append(("hr_agent", rng.choice(HR_HAPPY)))
            warm.append(("it_agent", rng.choice(IT_HAPPY)))
        for aid, text in warm[:30]:
            await _drive(client, agent_id=aid, text=text, label="warm")
            if delay > 0:
                await asyncio.sleep(delay)

        print("\n=== Phase 2 — Scenario A (slow injection) on router, 3 cycles ===")
        for cycle in range(3):
            for text in SLOW_INJECTION_TURNS:
                await _drive(client, agent_id="router", text=text, label=f"A.c{cycle+1}")
                if delay > 0:
                    await asyncio.sleep(delay)
            await asyncio.sleep(0.5)

        print("\n=== Phase 3 — recovery on router (10 benign turns) ===")
        for _ in range(10):
            text = rng.choice(ROUTER_HAPPY)
            await _drive(client, agent_id="router", text=text, label="A.rec")
            if delay > 0:
                await asyncio.sleep(delay)

        print("\n=== Phase 4 — Scenario B (trust-then-burst) on hr_agent ===")
        for _ in range(20):
            text = rng.choice(HR_HAPPY)
            await _drive(client, agent_id="hr_agent", text=text, label="B.warm")
            if delay > 0:
                await asyncio.sleep(delay)
        for i, text in enumerate(BURST_PROMPTS):
            await _drive(client, agent_id="hr_agent", text=text, label=f"B.burst{i+1}")
            if delay > 0:
                await asyncio.sleep(delay)

        print("\n=== Phase 5 — Scenario C (tool poisoning) on it_agent ===")
        for i, text in enumerate(POISONED_TOOL_TURNS):
            await _drive(client, agent_id="it_agent", text=text, label=f"C.t{i+1}")
            if delay > 0:
                await asyncio.sleep(delay)

        print("\nDemo run complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="LT-Sentinel canonical demo run")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="qwen2.5:7b")
    parser.add_argument("--qps", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=20260516)
    args = parser.parse_args()

    asyncio.run(run(base_url=args.base_url, model=args.model, qps=args.qps, seed=args.seed))


if __name__ == "__main__":
    main()
