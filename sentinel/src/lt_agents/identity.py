"""Per-worker identity declarations — feeds the `_lobstertrap` extra_body
metadata on every outbound LLM call so LT can compare declared-vs-detected
on real declared scopes (not the empty arrays the v1 demo used).

Each worker declares:
    declared_intent     — one of LT's IntentCategory tokens (general / data_access / etc.)
    declared_paths      — file paths the worker is allowed to touch
    declared_commands   — shell commands the worker may legitimately reference
    declared_domains    — outbound domains the worker may legitimately mention

Any value DPI extracts outside these declared scopes shows up as a
declared-vs-detected mismatch in LT's audit log — exactly the Veea bonus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    declared_intent: str
    declared_paths: tuple[str, ...]
    declared_commands: tuple[str, ...]
    declared_domains: tuple[str, ...]

    def as_lobstertrap_extra(self) -> dict:
        return {
            "_lobstertrap": {
                "agent_id": self.agent_id,
                "declared_intent": self.declared_intent,
                "declared_paths": list(self.declared_paths),
                "declared_commands": list(self.declared_commands),
                "declared_domains": list(self.declared_domains),
            }
        }


# Router has no resource access — it only classifies and dispatches.
ROUTER = AgentIdentity(
    agent_id="router",
    declared_intent="general",
    declared_paths=(),
    declared_commands=(),
    declared_domains=(),
)

# HR worker — reads HR policy docs, references its own workspace.
HR = AgentIdentity(
    agent_id="hr_agent",
    declared_intent="general",
    declared_paths=(
        "/home/agent_workspace/hr/policies/",
        "/tmp/agent_workspace/hr/",
    ),
    declared_commands=(),
    declared_domains=("chroma://hr_policy",),
)

# Finance worker — finance policy docs + workspace.
FINANCE = AgentIdentity(
    agent_id="finance_agent",
    declared_intent="general",
    declared_paths=(
        "/home/agent_workspace/finance/policies/",
        "/tmp/agent_workspace/finance/",
    ),
    declared_commands=(),
    declared_domains=("chroma://finance_policy",),
)

# IT worker — IT runbook docs + a narrow allowlist of safe shell commands
# (e.g. checking VPN status, listing tickets).
IT = AgentIdentity(
    agent_id="it_agent",
    declared_intent="general",
    declared_paths=(
        "/home/agent_workspace/it/runbooks/",
        "/tmp/agent_workspace/it/",
    ),
    declared_commands=("vpnstatus", "ticketstatus", "passwd-self-service"),
    declared_domains=("chroma://it_runbook",),
)


def all_identities() -> Iterable[AgentIdentity]:
    return (ROUTER, HR, FINANCE, IT)


def by_id(agent_id: str) -> AgentIdentity:
    for ident in all_identities():
        if ident.agent_id == agent_id:
            return ident
    raise KeyError(f"unknown agent_id: {agent_id!r}")
