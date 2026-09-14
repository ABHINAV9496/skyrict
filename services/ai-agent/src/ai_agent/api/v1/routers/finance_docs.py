"""/ai financi-docs LLM endpoints - tax summary (A5), audit narration (A10), doc Q&A (A12).

FIN-AI-004 upstream counterpart of the core ``/finance/ai`` proxy. Each endpoint
is stateless: core sends the tenant's period + posted entries (or the question)
in the body, ai-agent runs the LLM primitive in
:mod:`ai_agent.features.finance_docs.generate`, and returns strict JSON or
empty fields on abstention (``None``) so core can degrade gracefully.

Authentication (JWT re-verification + tenant cross-check) happens here via
``get_current_user``; authorization happens upstream at the core proxy
(``erp.finance.ai.read`` / ``erp.finance.ai.write``), matching the
account-suggest / finance-ai posture.

The A12 endpoint composes the shared RAG retrieval stack (same seam as
``routers/rag.py``) and feeds the retrieved chunks to the LLM as evidence.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.core.tenant_context import TenantContext
from ai_agent.core.token_counter import TokenCounter
from ai_agent.db.query_cache_repository import QueryCacheRepository
from ai_agent.db.rag_repository import RagRepository
from ai_agent.features.finance_docs.generate import (
    answer_question as llm_answer_question,
)
from ai_agent.features.finance_docs.generate import (
    generate_tax_summary as llm_generate_tax_summary,
)
from ai_agent.features.finance_docs.generate import (
    narrate_audit as llm_narrate_audit,
)
from ai_agent.features.rag.ingest.loader import SourceDocument
from ai_agent.features.rag.ingest.service import RagIngestService
from ai_agent.features.rag.retrieval import RedisQueryCache
from ai_agent.features.rag.retrieval.service import RagRetrievalService

# ---------------------------------------------------------------------------
# A5: tax summary
# ---------------------------------------------------------------------------


class TaxPeriodIn(BaseModel):
    id: str
    name: str
    start_date: str
    end_date: str
    is_closed: bool = False


class TaxSummaryPayload(BaseModel):
    period: TaxPeriodIn
    snapshot: dict[str, Any] = Field(default_factory=dict)


class TaxCategoryOut(BaseModel):
    category: str
    detail: str
    input_tax: float
    output_tax: float
    net: float


class TaxSummaryResponse(BaseModel):
    categories: list[TaxCategoryOut]
    total_input: float
    total_output: float
    model_used: str


tax_summary_router = APIRouter(prefix="/ai/tax-summary", tags=["ai-finance-docs"])


@tax_summary_router.post("/generate", response_model=TaxSummaryResponse)
async def generate_tax_summary(
    body: TaxSummaryPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> TaxSummaryResponse:
    """Per-category input/output tax for a fiscal period's posted entries."""
    entries = body.snapshot.get("entries") or []
    result = await llm_generate_tax_summary(
        request.app.state.llm_router,
        period=body.period.model_dump(),
        entries=entries,
    )
    if result is None:
        return TaxSummaryResponse(categories=[], total_input=0.0, total_output=0.0, model_used="")
    return TaxSummaryResponse(
        categories=[
            TaxCategoryOut(
                category=c.category,
                detail=c.detail,
                input_tax=c.input_tax,
                output_tax=c.output_tax,
                net=c.net,
            )
            for c in result.categories
        ],
        total_input=result.total_input,
        total_output=result.total_output,
        model_used=result.model_used,
    )


# ---------------------------------------------------------------------------
# A10: audit narration
# ---------------------------------------------------------------------------


class NarrationPayload(BaseModel):
    from_date: str
    to_date: str
    entries: list[dict[str, Any]] = Field(default_factory=list)


class RiskAreaOut(BaseModel):
    entry_id: str | None = None
    risk_type: str
    description: str
    severity: str


class NarrationResponse(BaseModel):
    narration: str
    risk_areas: list[RiskAreaOut]
    model_used: str


audit_narration_router = APIRouter(prefix="/ai/audit", tags=["ai-finance-docs"])


@audit_narration_router.post("/narration", response_model=NarrationResponse)
async def audit_narration(
    body: NarrationPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> NarrationResponse:
    """Plain-English narration + risk areas over posted entries in a range."""
    result = await llm_narrate_audit(
        request.app.state.llm_router,
        from_date=body.from_date,
        to_date=body.to_date,
        entries=body.entries,
    )
    if result is None:
        return NarrationResponse(narration="", risk_areas=[], model_used="")
    return NarrationResponse(
        narration=result.narration,
        risk_areas=[
            RiskAreaOut(
                entry_id=ra.entry_id,
                risk_type=ra.risk_type,
                description=ra.description,
                severity=ra.severity,
            )
            for ra in result.risk_areas
        ],
        model_used=result.model_used,
    )


# ---------------------------------------------------------------------------
# A12: document Q&A over RAG
# ---------------------------------------------------------------------------


class QaPayload(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class QaCitationOut(BaseModel):
    source_ref: str
    chunk_text: str
    score: float


class QaResponse(BaseModel):
    answer: str
    citations: list[QaCitationOut]
    model_used: str


doc_qa_router = APIRouter(prefix="/ai/rag", tags=["ai-finance-docs"])


def _build_retrieval_service(request: Request, session: AsyncSession) -> RagRetrievalService:
    """Compose the RAG retrieval stack (mirrors ``routers/rag.py``)."""
    provider = build_embedding_provider(settings)
    if provider is None:
        raise AiUnavailableError("No embedding provider configured - set AI_EMBEDDING_PROVIDER")
    return RagRetrievalService(
        embedding_provider=provider,
        store=RagRepository(session),
        cache=RedisQueryCache(),
        top_k_retrieve=settings.RAG_TOP_K_RETRIEVE,
        top_k_return=settings.RAG_TOP_K_RETURN,
        cache_ttl_seconds=settings.RAG_CACHE_TTL_SECONDS,
        rate_limit_per_minute=settings.RATE_LIMIT_RAG_SEARCH_PER_MIN,
        tenant_limit_per_minute=settings.RATE_LIMIT_TENANT_PER_MIN,
        persistent_cache=QueryCacheRepository(session),
    )


def get_rag_retrieval_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RagRetrievalService:
    """FastAPI dependency wrapping :func:`_build_retrieval_service`."""
    return _build_retrieval_service(request, session)


def _build_ingest_service(session: AsyncSession) -> RagIngestService:
    """Compose the RAG ingest stack (mirrors the ``ai-agent ingest`` runner)."""
    provider = build_embedding_provider(settings)
    if provider is None:
        raise AiUnavailableError("No embedding provider configured - set AI_EMBEDDING_PROVIDER")
    return RagIngestService(
        counter=TokenCounter(),
        embedding_provider=provider,
        store=RagRepository(session),
        child_tokens=settings.RAG_CHUNK_CHILD_TOKENS,
        parent_tokens=settings.RAG_CHUNK_PARENT_TOKENS,
        overlap_tokens=settings.RAG_CHUNK_OVERLAP_TOKENS,
    )


def _finance_source_document(source_ref: str, text: str, *, page_title: str = "") -> SourceDocument:
    """Build one ``finance-docs`` document; optional heading prefixes the body."""
    body = text if not page_title else f"## {page_title}\n\n{text}"
    return SourceDocument(module="finance-docs", source_ref=source_ref, text=body)


@doc_qa_router.post("/qa", response_model=QaResponse)
async def doc_qa(
    body: QaPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> QaResponse:
    """Answer a question over the tenant's RAG documents with citations."""
    service = _build_retrieval_service(request, session)
    retrieval = await service.search(
        query=body.question,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    evidence = [
        {"source_ref": item.source_ref, "chunk_text": item.chunk_text, "score": item.score}
        for item in retrieval.data
    ]
    result = await llm_answer_question(
        request.app.state.llm_router,
        question=body.question,
        evidence=evidence,
    )
    if result is None:
        return QaResponse(answer="", citations=[], model_used="")
    return QaResponse(
        answer=result.answer,
        citations=[
            QaCitationOut(
                source_ref=c.source_ref,
                chunk_text=c.chunk_text,
                score=c.score,
            )
            for c in result.citations
        ],
        model_used=result.model_used,
    )


# ---------------------------------------------------------------------------
# Finance-doc indexing into RAG (core pushes generated documents)
# ---------------------------------------------------------------------------


class FinanceDocIndexPayload(BaseModel):
    source_ref: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=10, max_length=200_000)
    page_title: str = Field(default="", max_length=200)


class FinanceDocIndexResponse(BaseModel):
    source_ref: str
    module: str
    parents: int
    children: int
    tokens_embedded: int
    model_used: str


@doc_qa_router.post("/index-finance-doc", response_model=FinanceDocIndexResponse)
async def index_finance_doc(
    body: FinanceDocIndexPayload,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> FinanceDocIndexResponse:
    """Store one generated finance document into the caller tenant's RAG store.

    Idempotent by ``source_ref`` (existing rows are replaced), so re-indexing a
    regenerated document converges instead of stacking duplicates. The tenant
    security context is pinned before any write, same as the ingest runner.
    """
    tenant_id = user["tenant_id"]
    if not isinstance(tenant_id, uuid.UUID):
        tenant_id = uuid.UUID(str(tenant_id))
    TenantContext.set(str(tenant_id))

    source = _finance_source_document(body.source_ref, body.text, page_title=body.page_title)
    report = await _build_ingest_service(session).ingest(tenant_id=tenant_id, documents=[source])
    await session.commit()
    return FinanceDocIndexResponse(
        source_ref=body.source_ref,
        module=source.module,
        parents=report.parents,
        children=report.children,
        tokens_embedded=report.tokens_embedded,
        model_used=report.model_used,
    )
