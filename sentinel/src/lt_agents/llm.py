"""Per-agent OpenAI-compatible client factory.

Every LangGraph node that calls an LLM uses one of these clients. The
`_lobstertrap` field is injected via `extra_body`, which the OpenAI SDK
merges into the chat-completion request payload — Sentinel's reverse proxy
forwards that to LT, LT writes `agent_id` and `declared_*` into its audit
log, and our cross-event monitor sees the right identity.

This is the integration point that makes per-agent governance real.
"""

from __future__ import annotations

import os

from langchain_openai import ChatOpenAI

from .identity import AgentIdentity


DEFAULT_BASE_URL = os.environ.get("LT_SENTINEL_BASE", "http://127.0.0.1:8080/v1")
DEFAULT_MODEL = os.environ.get("LT_AGENTS_MODEL", "qwen2.5:7b")
DEFAULT_API_KEY = os.environ.get("LT_AGENTS_API_KEY", "ollama-no-key")


def build_chat(
    identity: AgentIdentity,
    *,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    api_key: str = DEFAULT_API_KEY,
    temperature: float = 0.1,
    max_tokens: int = 256,
) -> ChatOpenAI:
    """Return a ChatOpenAI bound to one agent's identity declarations.

    `extra_body` carries the `_lobstertrap` extension field, which LT reads
    via the standard non-standard chat-completion request extension protocol
    documented in `internal/proxy/openai.go`.
    """
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=identity.as_lobstertrap_extra(),
    )
