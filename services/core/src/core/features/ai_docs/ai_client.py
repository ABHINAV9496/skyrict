"""Core -> ai-agent LLM relay for the AI-docs feature (FIN-AI-004).

Mirrors ``core.features.finance.ai_suggester``: core serializes the tenant's
finance context in-body and relays it to stateless ai-agent endpoints
(``POST /api/v1/ai/tax-summary/generate``, ``POST /api/v1/ai/audit/narration``,
``POST /api/v1/ai/rag/qa``). ``Authorization`` + tenant slug are relayed so
ai-agent re-verifies the JWT and tenant every call. Transport failures surface
as :class:`AiServiceUnavailableError`; upstream HTTP errors (4xx/5xx) return
``None`` so callers can degrade gracefully (e.g. retry with a deterministic
fallback) instead of masking real provider problems.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from core.core.exceptions import AiServiceUnavailableError
from core.features.ai.proxy import forward_to_ai_agent

_TAX_UPSTREAM_PATH = "/api/v1/ai/tax-summary/generate"
_NARRATION_UPSTREAM_PATH = "/api/v1/ai/audit/narration"
_QA_UPSTREAM_PATH = "/api/v1/ai/rag/qa"
_INDEX_UPSTREAM_PATH = "/api/v1/ai/rag/index-finance-doc"


async def _relay(
    client: httpx.AsyncClient,
    *,
    upstream_path: str,
    authorization: str | None,
    tenant_slug: str | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    upstream = await forward_to_ai_agent(
        client,
        method="POST",
        upstream_path=upstream_path,
        authorization=authorization,
        tenant_slug=tenant_slug,
        body=json.dumps(payload, default=str).encode("utf-8"),
    )
    if upstream.status_code >= 400:
        return None
    try:
        data = upstream.json()
    except ValueError:
        raise AiServiceUnavailableError(f"AI relay {upstream_path} returned invalid JSON") from None
    return data if isinstance(data, dict) else None


async def generate_tax_summary_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    period: dict[str, Any],
    snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    """Ask ai-agent's LLM for per-category input/output tax; ``None`` on abstention."""
    payload = {"period": period, "snapshot": snapshot}
    data = await _relay(
        client,
        upstream_path=_TAX_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        payload=payload,
    )
    categories = data.get("categories") if data else None
    if not isinstance(categories, list) or not categories:
        return None
    return data


async def narrate_audit_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    from_date: str,
    to_date: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Ask ai-agent for a change narrative + risk areas over posted entries."""
    payload = {"from_date": from_date, "to_date": to_date, "entries": entries}
    return await _relay(
        client,
        upstream_path=_NARRATION_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        payload=payload,
    )


async def answer_question_with_ai(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    question: str,
) -> dict[str, Any] | None:
    """Ask ai-agent's RAG pipeline over the tenant's finance documents."""
    return await _relay(
        client,
        upstream_path=_QA_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        payload={"question": question},
    )


async def index_finance_doc_in_rag(
    client: httpx.AsyncClient,
    *,
    authorization: str | None,
    tenant_slug: str | None,
    source_ref: str,
    text: str,
    page_title: str = "",
) -> bool:
    """Index one generated finance document into the tenant's RAG store.

    Best-effort from the caller's side: ``False`` on an upstream refusal, an
    exception on transport failure - indexing must never block document
    generation, so callers should swallow failures.
    """
    data = await _relay(
        client,
        upstream_path=_INDEX_UPSTREAM_PATH,
        authorization=authorization,
        tenant_slug=tenant_slug,
        payload={"source_ref": source_ref, "text": text, "page_title": page_title},
    )
    return bool(data and data.get("source_ref"))
