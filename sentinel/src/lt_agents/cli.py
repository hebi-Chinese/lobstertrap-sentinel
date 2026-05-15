"""Tiny CLI for ad-hoc testing of the agent graph.

    py -m lt_agents.cli ask "What is the PTO carry-over policy?"
    py -m lt_agents.cli ask "How do I reset my SSO password?" --print-trace
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from .graph import arun_one, build_graph


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _default_chroma_dir() -> Path:
    # sentinel/src/lt_agents/cli.py  →  sentinel/data/chroma_seed/
    return Path(__file__).resolve().parents[2] / "data" / "chroma_seed"


@click.group()
@click.option("--verbose", "-v", is_flag=True)
def main(verbose: bool) -> None:
    _configure_logging(verbose)


@main.command("ask")
@click.argument("user_text")
@click.option("--chroma-dir", type=Path, default=None)
@click.option("--print-trace", is_flag=True, help="Print every message in the final state.")
def ask_cmd(user_text: str, chroma_dir: Path | None, print_trace: bool) -> None:
    chroma_dir = chroma_dir or _default_chroma_dir()
    graph = build_graph(chroma_dir)

    async def _go() -> None:
        state = await arun_one(graph, user_text)
        msgs: list[BaseMessage] = state.get("messages", [])
        routed = state.get("routed_to", "?")
        click.echo(f"\nrouted_to: {routed}")
        click.echo(f"messages : {len(msgs)}\n")
        for i, m in enumerate(msgs):
            kind = type(m).__name__
            tag = ""
            if isinstance(m, AIMessage) and m.tool_calls:
                tag = f" [tool_calls={[c['name'] for c in m.tool_calls]}]"
            if isinstance(m, ToolMessage):
                tag = f" [tool={m.name}]"
            content = (m.content or "").strip()
            preview = content if print_trace else content[:240]
            click.echo(f"  [{i}] {kind}{tag}: {preview}")
        # Final reply
        final = next((m for m in reversed(msgs) if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)), None)
        click.echo("\nFINAL REPLY:")
        click.echo(final.content if final else "(no AI reply)")

    asyncio.run(_go())


@main.command("seed")
@click.option("--chroma-dir", type=Path, default=None)
def seed_cmd(chroma_dir: Path | None) -> None:
    from .rag import seed_corpora
    chroma_dir = chroma_dir or _default_chroma_dir()
    seed_corpora(chroma_dir)
    click.echo(f"Seeded Chroma at {chroma_dir}")


if __name__ == "__main__":
    main()
