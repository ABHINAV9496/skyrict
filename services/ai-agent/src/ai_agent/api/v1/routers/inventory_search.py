"""/ai/inventory/search - hybrid product search (SKY-70).

Authentication happens here (JWT verified + tenant cross-check); authorization
happened upstream at the core monolith's proxy (erp.inventory.read checked
before forwarding - the SKY-57 "AI is a proxy, not a bypass" rule). The core
proxy also decides whether this caller may see valuation data: it forwards
``X-AI-Valuation-Disclosed: 1`` ONLY when the caller holds
``erp.inventory.valuation``, and this router attaches cost prices only when
that header is present.

Unlike the RAG endpoint, a missing embedding provider is NOT an error here:
the service degrades to exact-only search (``degraded=true``) so the catalog
stays searchable.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.inventory_search import (
    InventorySearchItem,
    InventorySearchResponse,
)
from ai_agent.core.config import settings
from ai_agent.core.embedding import build_embedding_provider
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.inventory_embedding_repository import InventoryEmbeddingRepository
from ai_agent.db.query_log_repository import QueryLogRepository
from ai_agent.features.inventory_semantic.search import (
    InventorySearchItem as InventorySearchItemFeature,
)
from ai_agent.features.inventory_semantic.search import InventorySearchService
from ai_agent.features.nl_query.gateway import HttpInventoryGateway, InventoryGatewayPort
from ai_agent.features.rag.retrieval import RedisQueryCache

router = APIRouter(prefix="/ai/inventory", tags=["ai-inventory-search"])

_VALUATION_HEADER = "X-AI-Valuation-Disclosed"


def get_inventory_gateway(request: Request) -> InventoryGatewayPort:
    """Gateway bound to THIS request's identity - never service credentials.

    Core sees the caller's own JWT and tenant slug, so warehouse filtering and
    valuation reads run with exactly the access the human user already has.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return HttpInventoryGateway(
        base_url=str(settings.INVENTORY_SERVICE_URL),
        bearer_token=token,
        tenant_slug=TenantContext.get_tenant_slug() or "",
    )


def _build_service(request: Request, session: AsyncSession) -> InventorySearchService:
    """Compose the search stack for one request (test-visible seam)."""
    valuation_disclosed = request.headers.get(_VALUATION_HEADER) == "1"
    return InventorySearchService(
        embedding_provider=build_embedding_provider(settings),
        store=InventoryEmbeddingRepository(session),
        cache=RedisQueryCache(key_prefix="ai:inv:search:cache:"),
        gateway=get_inventory_gateway(request) if valuation_disclosed else None,
        query_logs=QueryLogRepository(session),
        limit=settings.INV_SEARCH_DEFAULT_LIMIT,
        semantic_top_k=settings.INV_SEARCH_SEMANTIC_TOP_K,
        cache_ttl_seconds=settings.INV_SEARCH_CACHE_TTL_SECONDS,
        rate_limit_per_minute=settings.RATE_LIMIT_INV_SEARCH_PER_MIN,
        tenant_limit_per_minute=settings.RATE_LIMIT_TENANT_PER_MIN,
    )


def get_inventory_search_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InventorySearchService:
    """FastAPI dependency wrapping :func:`_build_service`."""
    return _build_service(request, session)


@router.get("/search", response_model=InventorySearchResponse)
async def inventory_search(
    request: Request,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[InventorySearchService, Depends(get_inventory_search_service)],
    warehouse_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> InventorySearchResponse:
    """Hybrid product search over this tenant's snapshot.

    Exact substring hits rank above semantic vector hits, merged and
    deduplicated by product. Identical queries hit the Redis hot cache
    (``cached=true``). Warehouse scoping and valuation prices are best-effort
    side channels gated by the forwarded identity.
    """
    result = await service.search(
        query=q,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        warehouse_id=warehouse_id,
        limit=limit,
        valuation_enabled=request.headers.get(_VALUATION_HEADER) == "1",
    )
    return InventorySearchResponse(
        data=[_to_schema_item(item) for item in result.data],
        cached=result.cached,
        degraded=result.degraded,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )


def _to_schema_item(item: InventorySearchItemFeature) -> InventorySearchItem:
    return InventorySearchItem(
        item_id=item.item_id,
        sku=item.sku,
        name=item.name,
        category=item.category,
        unit=item.unit,
        source=item.source,
        score=item.score,
        matched_fields=item.matched_fields,
        cost_price=item.cost_price,
    )
