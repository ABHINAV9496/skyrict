"""/ai/query endpoints - natural-language inventory questions (spec §2.5).

Authentication happens here; authorization happened upstream at the core
monolith's proxy (erp.inventory.read checked before forwarding - the SKY-57
"AI is a proxy, not a bypass" rule). This router composes per-request
dependencies: caller identity, an inventory gateway bound to the CALLER'S
token, and the engine wired to the shared LLM router from app.state.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.nl_query import (
    NlQueryRequest,
    NlQueryResponse,
    QueryHistoryItem,
    QueryHistoryResponse,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.query_log_repository import QueryLogRepository
from ai_agent.features.nl_query.engine import NlQueryEngine
from ai_agent.features.nl_query.gateway import HttpInventoryGateway, InventoryGatewayPort
from ai_agent.features.nl_query.service import NlQueryService

router = APIRouter(prefix="/ai/query", tags=["ai-query"])


def get_inventory_gateway(request: Request) -> InventoryGatewayPort:
    """Gateway bound to THIS request's identity - never service credentials.

    Core sees the caller's own JWT and tenant slug, so every inventory read
    runs with exactly the access the human user already has.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return HttpInventoryGateway(
        base_url=str(settings.INVENTORY_SERVICE_URL),
        bearer_token=token,
        # Middleware guarantees the slug exists on business routes.
        tenant_slug=TenantContext.get_tenant_slug() or "",
    )


def _build_service(
    request: Request,
    session: AsyncSession,
) -> NlQueryService:
    """Compose the NL-query stack for one request (test-visible seam)."""
    gateway = get_inventory_gateway(request)

    async def gateway_factory() -> InventoryGatewayPort:
        return gateway

    engine = NlQueryEngine(
        llm_router=request.app.state.llm_router,
        gateway_factory=gateway_factory,
        confidence_threshold=settings.CONFIDENCE_THRESHOLD,
    )
    return NlQueryService(
        engine=engine,
        query_logs=QueryLogRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
        rate_limit_per_minute=settings.RATE_LIMIT_NL_QUERY_PER_MIN,
        tenant_limit_per_minute=settings.RATE_LIMIT_TENANT_PER_MIN,
    )


def get_nl_query_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NlQueryService:
    """FastAPI dependency wrapping :func:`_build_service`."""
    return _build_service(request, session)


@router.post("", response_model=NlQueryResponse)
async def submit_query(
    body: NlQueryRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[NlQueryService, Depends(get_nl_query_service)],
) -> NlQueryResponse:
    """Answer one natural-language question about this tenant's stock."""
    result = await service.ask(
        question=body.query,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    return NlQueryResponse(
        answer=result.answer,
        data=result.data,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )


@router.get("/history", response_model=QueryHistoryResponse)
async def query_history(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> QueryHistoryResponse:
    """Recent queries for this tenant (newest first)."""
    rows = await QueryLogRepository(session).list_for_tenant(tenant_id=user["tenant_id"])
    items = [QueryHistoryItem.model_validate(row) for row in rows]
    return QueryHistoryResponse(data=items)
