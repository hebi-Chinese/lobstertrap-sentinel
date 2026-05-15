"""lt_agents — LangGraph-based multi-agent system that sits in front of LT-Sentinel.

A user request enters the Router node which classifies it into one of three
domains (HR / Finance / IT) and forwards to the matching worker. Each worker
has its own scoped Chroma-backed tool for retrieving policy documents. All
LLM calls (Router + workers) flow through the Sentinel proxy on :8080, with
per-agent `_lobstertrap` declared metadata so LT's declared-vs-detected
mismatch detection works on real data.

This realises DESIGN.md §11.4's "agents" process group with real agent loop,
real tool calling (role: tool messages), and real per-worker declared scope.
"""

__version__ = "0.1.0"
