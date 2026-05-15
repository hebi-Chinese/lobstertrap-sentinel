"""Shared OpenAI-compatible client that talks to Sentinel proxy on :8080.

Keeps the scenarios small: each scenario just imports `send_chat` and feeds
`ScriptedTurn` instances.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass
class ChatResult:
    request_id: str
    verdict: str
    rule_name: str
    rejected: bool
    reply_text: str
    raw: dict


class SentinelClient:
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8080",
        model: str = "qwen3:8b",
        timeout_s: float = 60.0,
        max_tokens: int = 12,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "SentinelClient":
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout_s)
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def send_chat(
        self,
        *,
        agent_id: str,
        declared_intent: str,
        user_text: str,
        declared_paths: list[str] | None = None,
        declared_commands: list[str] | None = None,
        declared_domains: list[str] | None = None,
        role: str = "user",
        history: list[dict] | None = None,
    ) -> ChatResult:
        assert self._session is not None, "Use 'async with SentinelClient(...)'"

        messages: list[dict] = list(history or [])
        messages.append({"role": role, "content": user_text})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": False,
            "_lobstertrap": {
                "agent_id": agent_id,
                "declared_intent": declared_intent,
                "declared_paths": declared_paths or [],
                "declared_commands": declared_commands or [],
                "declared_domains": declared_domains or [],
            },
        }

        async with self._session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
        ) as resp:
            data = await resp.json()

        meta = data.get("_lobstertrap") or {}
        ingress = meta.get("ingress") or {}
        verdict = str(meta.get("verdict") or "")
        rule_name = str(ingress.get("rule_name") or "")
        rejected = verdict.upper() in {"DENY", "HUMAN_REVIEW", "QUARANTINE"}
        reply = ""
        choices = data.get("choices") or []
        if choices:
            reply = (choices[0].get("message") or {}).get("content") or ""

        return ChatResult(
            request_id=str(meta.get("request_id") or ""),
            verdict=verdict,
            rule_name=rule_name,
            rejected=rejected,
            reply_text=reply,
            raw=data,
        )
