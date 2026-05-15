"""LangGraph StateGraph wiring — Router + 3 workers + 3 tool nodes.

Topology (DESIGN.md §2.1 made real):

                  ┌──────────────────────────┐
                  │ Router (LLM classifier)  │
                  └────────────┬─────────────┘
                               │ conditional edge by chosen worker
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
       ┌────────┐        ┌──────────┐        ┌────────┐
       │   HR   │ ─┐     │ Finance  │ ─┐     │   IT   │ ─┐
       └────────┘  │     └──────────┘  │     └────────┘  │
            ▲      │           ▲       │          ▲      │
            │  tool│           │  tool │          │ tool │
            │ call│            │ call  │          │ call │
            │      ▼           │       ▼          │      ▼
       ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
       │ HR ToolNode │    │Finance Tool  │    │ IT ToolNode │
       └─────────────┘    └──────────────┘    └─────────────┘

Every LLM call inside this graph routes through Sentinel:8080 → LT → backend.
Sentinel sees per-agent audit-log entries with correct agent_id / declared_*.
"""

from __future__ import annotations

import logging
import operator
from typing import Annotated, Callable, TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from . import identity as ident
from .llm import build_chat
from .rag import build_tools

logger = logging.getLogger(__name__)


# ---- state -----------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """LangGraph state. messages accumulates across all turns."""

    messages: Annotated[list[BaseMessage], operator.add]
    routed_to: str  # one of "hr" / "finance" / "it"


# ---- Router ----------------------------------------------------------------


ROUTER_SYSTEM_PROMPT = (
    "You are AcmeCorp's internal routing assistant. Classify the user's request "
    "into exactly one of the three teams that can answer it: HR, FINANCE, or IT.\n\n"
    "Respond with EXACTLY one token — HR, FINANCE, or IT — and nothing else.\n\n"
    "Examples:\n"
    "  Q: 'What is the PTO carry-over policy?' → HR\n"
    "  Q: 'How do I submit an expense report?' → FINANCE\n"
    "  Q: 'How do I reset my SSO password?' → IT\n"
    "If the request is unclear, default to HR."
)


def _router_node_factory() -> Callable[[AgentState], dict]:
    llm = build_chat(ident.ROUTER, temperature=0.0, max_tokens=8)

    def router_node(state: AgentState) -> dict:
        last_user = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        if last_user is None:
            return {"routed_to": "hr"}

        decision = llm.invoke(
            [
                SystemMessage(content=ROUTER_SYSTEM_PROMPT),
                HumanMessage(content=last_user.content),
            ]
        )
        token = (decision.content or "").strip().upper()
        if "FINANCE" in token:
            target = "finance"
        elif "IT" in token:
            target = "it"
        else:
            target = "hr"
        logger.info("router decision: %r → %s", token, target)
        return {"routed_to": target}

    return router_node


# ---- Workers ---------------------------------------------------------------


def _worker_system_prompt(domain: str) -> str:
    return (
        f"You are AcmeCorp's internal {domain} assistant. Answer the user's "
        f"question using AcmeCorp {domain} policy. If the question can be "
        f"answered directly from your knowledge of standard practice, do so. "
        f"If you need specific AcmeCorp policy detail, call the appropriate "
        f"search tool exactly once. Keep your answer under 80 words."
    )


def _worker_node_factory(
    identity: ident.AgentIdentity,
    domain: str,
    tool,
) -> Callable[[AgentState], dict]:
    llm = build_chat(identity, temperature=0.2, max_tokens=160)
    bound_tools = list(tool) if isinstance(tool, (list, tuple)) else [tool]
    llm_with_tools = llm.bind_tools(bound_tools)

    sys_prompt = _worker_system_prompt(domain)

    def worker_node(state: AgentState) -> dict:
        msgs = [SystemMessage(content=sys_prompt)] + list(state["messages"])
        try:
            response = llm_with_tools.invoke(msgs)
        except Exception as exc:
            # LT may DENY the request — that's a normal part of the demo and
            # we want it captured in the audit log, not a Python exception.
            logger.warning("%s LLM call rejected: %s", identity.agent_id, exc)
            response = AIMessage(
                content=f"[{identity.agent_id}] request rejected by guardrail."
            )
        return {"messages": [response]}

    return worker_node


# ---- Graph builder ---------------------------------------------------------


def _has_tool_calls(state: AgentState) -> bool:
    if not state.get("messages"):
        return False
    last = state["messages"][-1]
    return isinstance(last, AIMessage) and bool(getattr(last, "tool_calls", None))


def _route_to_worker(state: AgentState) -> str:
    return state.get("routed_to", "hr")


def build_graph(chroma_persist_dir, *, extra_it_tools=None):
    """Compile and return a runnable LangGraph app.

    `extra_it_tools` lets a scenario inject additional tools into the IT
    worker — used by Scenario C (tool poisoning) to bind a deliberately
    compromised external-data tool that returns escalating payloads.
    The injected tool flows through the real ToolNode so its return value
    arrives as a proper `role:"tool"` message and LT can inspect it.
    """
    tools = build_tools(chroma_persist_dir)

    it_tool_list = [tools["it"]]
    if extra_it_tools:
        it_tool_list.extend(extra_it_tools)

    router_node = _router_node_factory()
    hr_node = _worker_node_factory(ident.HR, "HR", tools["hr"])
    finance_node = _worker_node_factory(ident.FINANCE, "Finance", tools["finance"])
    it_node = _worker_node_factory(ident.IT, "IT", it_tool_list)

    hr_tools = ToolNode([tools["hr"]])
    finance_tools = ToolNode([tools["finance"]])
    it_tools = ToolNode(it_tool_list)

    graph = StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("hr", hr_node)
    graph.add_node("finance", finance_node)
    graph.add_node("it", it_node)
    graph.add_node("hr_tools", hr_tools)
    graph.add_node("finance_tools", finance_tools)
    graph.add_node("it_tools", it_tools)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _route_to_worker,
        {"hr": "hr", "finance": "finance", "it": "it"},
    )

    # Each worker either calls its tool or finishes.
    graph.add_conditional_edges(
        "hr", lambda s: "hr_tools" if _has_tool_calls(s) else END, {"hr_tools": "hr_tools", END: END}
    )
    graph.add_conditional_edges(
        "finance", lambda s: "finance_tools" if _has_tool_calls(s) else END, {"finance_tools": "finance_tools", END: END}
    )
    graph.add_conditional_edges(
        "it", lambda s: "it_tools" if _has_tool_calls(s) else END, {"it_tools": "it_tools", END: END}
    )

    # After a tool returns, give the worker one more chance to produce the
    # final answer with the retrieved context.
    graph.add_edge("hr_tools", "hr")
    graph.add_edge("finance_tools", "finance")
    graph.add_edge("it_tools", "it")

    return graph.compile()


# ---- public run helper -----------------------------------------------------


async def arun_one(graph, user_text: str) -> dict:
    """Single-turn entrypoint used by scenario scripts."""
    initial: AgentState = {"messages": [HumanMessage(content=user_text)]}
    final_state = await graph.ainvoke(initial)
    return final_state


def run_one(graph, user_text: str) -> dict:
    initial: AgentState = {"messages": [HumanMessage(content=user_text)]}
    return graph.invoke(initial)
