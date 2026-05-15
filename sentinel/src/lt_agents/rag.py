"""Chroma RAG store + per-worker retrieval tools.

Three persisted collections — `hr_policy`, `finance_policy`, `it_runbook`.
On first run we seed them from `corpus.py`; subsequent runs reuse the data
on disk. Each collection has its own retrieval function bound to one of
LangChain's `@tool` decorators so they show up as real OpenAI tool calls
in the agent's tool list (and therefore in LT's audit trail with proper
`role:"tool"` semantics).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import chromadb
from chromadb.config import Settings
from langchain_core.tools import tool

from .corpus import PolicyDoc, all_corpora

logger = logging.getLogger(__name__)


_CLIENT: chromadb.ClientAPI | None = None


def _get_client(persist_dir: Path) -> chromadb.ClientAPI:
    global _CLIENT
    if _CLIENT is None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        _CLIENT = chromadb.PersistentClient(
            path=str(persist_dir),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
    return _CLIENT


def seed_corpora(persist_dir: Path) -> None:
    """Idempotent — only inserts docs that aren't already present."""
    client = _get_client(persist_dir)
    for collection_name, docs in all_corpora().items():
        col = client.get_or_create_collection(name=collection_name)
        existing = set(col.get(ids=[d.doc_id for d in docs]).get("ids") or [])
        new_docs = [d for d in docs if d.doc_id not in existing]
        if not new_docs:
            logger.info("collection %s already seeded (%d docs)", collection_name, len(docs))
            continue
        col.add(
            ids=[d.doc_id for d in new_docs],
            documents=[f"{d.title}\n\n{d.body}" for d in new_docs],
            metadatas=[
                {"title": d.title, "doc_id": d.doc_id, "tags": ",".join(d.tags)}
                for d in new_docs
            ],
        )
        logger.info("seeded %s with %d new docs", collection_name, len(new_docs))


def _build_retrieval(collection_name: str, persist_dir: Path) -> Callable[[str], str]:
    def _retrieve(query: str) -> str:
        client = _get_client(persist_dir)
        col = client.get_collection(name=collection_name)
        result = col.query(query_texts=[query], n_results=3)
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        if not docs:
            return f"(no documents found in {collection_name} for query: {query!r})"
        lines = []
        for doc, meta in zip(docs, metas):
            title = (meta or {}).get("title", "untitled")
            lines.append(f"### {title}\n{doc.strip()}")
        return "\n\n".join(lines)

    return _retrieve


def build_tools(persist_dir: Path) -> dict[str, object]:
    """Return one LangChain @tool per worker. Tools are scoped to that
    worker's collection so HR can't query Finance docs, etc.
    """
    seed_corpora(persist_dir)

    hr_retrieve = _build_retrieval("hr_policy", persist_dir)
    finance_retrieve = _build_retrieval("finance_policy", persist_dir)
    it_retrieve = _build_retrieval("it_runbook", persist_dir)

    @tool("search_hr_policy")
    def search_hr_policy(query: str) -> str:
        """Search AcmeCorp HR policy documents. Use this for questions about
        paid time off, parental leave, remote work, handbook, referrals, and
        other people-related policies. Returns up to three matching policy
        excerpts."""
        return hr_retrieve(query)

    @tool("search_finance_policy")
    def search_finance_policy(query: str) -> str:
        """Search AcmeCorp finance policy documents. Use this for questions
        about expense reimbursement, per-diem limits, vendor onboarding,
        budget deadlines, and software purchase approvals."""
        return finance_retrieve(query)

    @tool("search_it_runbook")
    def search_it_runbook(query: str) -> str:
        """Search AcmeCorp IT runbook documents. Use this for questions
        about SSO password reset, VPN usage, laptop refresh, multi-factor
        authentication, and network incident SLAs."""
        return it_retrieve(query)

    return {
        "hr": search_hr_policy,
        "finance": search_finance_policy,
        "it": search_it_runbook,
    }
