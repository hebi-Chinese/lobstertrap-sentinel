"""Helper that lets scenarios drive the real LangGraph multi-agent system.

A scenario imports `GraphRunner`, builds it once, then calls `await
runner.user_turn(user_text)` per attack step. Errors (LT denial, tool
errors) are caught and surfaced as a structured `TurnOutcome` instead
of crashing the scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from lt_agents.graph import arun_one, build_graph


def _default_chroma_dir() -> Path:
    # scenarios/graph_runner.py → sentinel/data/chroma_seed/
    return Path(__file__).resolve().parents[1] / "data" / "chroma_seed"


@dataclass
class TurnOutcome:
    user_text: str
    routed_to: str
    n_messages: int
    tool_called: str | None
    final_reply: str
    error: str | None = None

    @property
    def short(self) -> str:
        tag = self.tool_called or "-"
        body = (self.final_reply or "(none)").replace("\n", " ")[:80]
        return f"route={self.routed_to:7s} tool={tag:24s} reply={body!r}"


class GraphRunner:
    def __init__(self, chroma_dir: Path | None = None) -> None:
        self._chroma_dir = chroma_dir or _default_chroma_dir()
        self._graph = build_graph(self._chroma_dir)

    async def user_turn(self, user_text: str) -> TurnOutcome:
        try:
            state: dict[str, Any] = await arun_one(self._graph, user_text)
        except Exception as exc:
            return TurnOutcome(
                user_text=user_text,
                routed_to="?",
                n_messages=0,
                tool_called=None,
                final_reply="",
                error=f"{type(exc).__name__}: {exc}",
            )

        msgs: list[BaseMessage] = list(state.get("messages", []))
        routed = state.get("routed_to", "?")

        tool_called: str | None = None
        for m in msgs:
            if isinstance(m, ToolMessage):
                tool_called = m.name
                break

        final = next(
            (m for m in reversed(msgs) if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None)),
            None,
        )
        final_text = (final.content or "").strip() if final else ""

        return TurnOutcome(
            user_text=user_text,
            routed_to=routed,
            n_messages=len(msgs),
            tool_called=tool_called,
            final_reply=final_text,
        )
