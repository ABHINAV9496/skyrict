"""/ai/rag endpoints — semantic search + store status (SKY-58).

Mirrors the nl_query router composition style: authentication is enforced via
``get_current_user`` (JWT verified + tenant cross-check); authorization is
enforced upstream at the core monolith proxy (SKY-57 "AI is a proxy, not a
bypass"). Each request wires the retrieval stack: the SHARED embedding
provider, a repository bound to the request session, and the Redis hot cache.

Simple retrieval (no generation call) needs no LLM provider — only an
embedding provider; a missing one degrades to a typed 503 via
``AiUnavailableError`` exactly like the NL path degrades without an LLM.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.rag import (
    RagModuleStatus,
    RagSearchItem,
    RagSearchRequest,
    RagSearchResponse,
    RagStatusResponse,
)
from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.db.query_cache_repository import QueryCacheRepository
from ai_agent.db.rag_repository import RagRepository
from ai_agent.features.rag.retrieval import RedisQueryCache
from ai_agent.features.rag.retrieval.service import RagRetrievalService

router = APIRouter(prefix="/ai/rag", tags=["ai-rag"])


def _build_service(request: Request, session: AsyncSession) -> RagRetrievalService:
    """Compose the retrieval stack for one request (test-visible seam)."""
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
    """FastAPI dependency wrapping :func:`_build_service`."""
    return _build_service(request, session)


@router.post("/search", response_model=RagSearchResponse)
async def rag_search(
    body: RagSearchRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[RagRetrievalService, Depends(get_rag_retrieval_service)],
) -> RagSearchResponse:
    """Semantic search over this tenant's RAG store using parent context.

    Retrieves child chunks by cosine similarity, collapses hits per parent,
    and returns up to ``AI_RAG_TOP_K_RETURN`` parent chunks for LLM context
    generation. Identical queries hit the Redis hot cache (``cached=true``).
    """
    result = await service.search(
        query=body.query,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    return RagSearchResponse(
        data=[
            RagSearchItem(
                parent_id=item.parent_id,
                source_ref=item.source_ref,
                module=item.module,
                chunk_text=item.chunk_text,
                score=item.score,
                child_hits=item.child_hits,
                metadata=item.metadata_,
            )
            for item in result.data
        ],
        cached=result.cached,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )


@router.get("/status", response_model=RagStatusResponse)
async def rag_status(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RagStatusResponse:
    """Per-module ingest counts and recent-ingest timestamps for the tenant."""
    modules = await RagRepository(session).status_for_tenant(tenant_id=user["tenant_id"])
    items = [RagModuleStatus.model_validate(row) for row in modules]
    return RagStatusResponse(
        modules=items,
        total_parents=sum(item.parents for item in items),
        total_children=sum(item.children for item in items),
    )
