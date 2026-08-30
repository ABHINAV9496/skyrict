"""/ai/narrator endpoints - the cross-module executive digest (SKY-63).

Authentication happens here; module-read authorization ({erp.finance.read,
erp.sales.read, erp.inventory.read, erp.crm.read} + erp.ai.invoke) happens
upstream at the core monolith proxy BEFORE forwarding, so a request reaching
this service has already passed the permission gate. The force-refresh action
is gated at the same edge by ``erp.ai.narrator.refresh``; the default here
allows it (the edge decides), with a seam for tests/tighter deployments.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.narrator import DigestResponse
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.digest_repository import DigestCacheRepository
from ai_agent.features.narrator.gateway import CoreGatewayPort, HttpCoreGateway
from ai_agent.features.narrator.service import NarratorService

router = APIRouter(prefix="/ai/narrator", tags=["ai-narrator"])


def get_core_gateway(request: Request) -> CoreGatewayPort:
    """Gateway bound to THIS request's identity - never service credentials."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return HttpCoreGateway(
        base_url=str(settings.INVENTORY_SERVICE_URL),
        bearer_token=token,
        tenant_slug=TenantContext.get_tenant_slug() or "",
    )


def get_refresh_allowed() -> bool:
    """The edge (core proxy) enforces ``erp.ai.narrator.refresh``; allow here.

    Returned as a plain value so the service's refresh gate defaults to allow;
    deployments that want to fail closed can override this dependency.
    """
    return True


def _build_service(
    request: Request,
    session: AsyncSession,
    allow_refresh: bool,
) -> NarratorService:
    gateway = get_core_gateway(request)
    return NarratorService(
        gateway=gateway,
        llm_router=request.app.state.llm_router,
        cache=DigestCacheRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
        allow_llm=settings.NARRATOR_ALLOW_LLM,
        allow_refresh=allow_refresh,
    )


def get_narrator_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    allow_refresh: Annotated[bool, Depends(get_refresh_allowed)],
) -> NarratorService:
    """FastAPI dependency wrapping :func:`_build_service`."""
    return _build_service(request, session, allow_refresh)


def _response(result: Any) -> DigestResponse:
    return DigestResponse(
        status=result.status,
        source=result.source,
        as_of=result.as_of,
        title=result.title,
        summary=result.summary,
        points=list(result.points),
        caveat=result.caveat,
        generated_at=result.generated_at,
        model_used=result.model_used,
        signals=result.signals or None,
    )


@router.get("/digest", response_model=DigestResponse)
async def get_digest(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[NarratorService, Depends(get_narrator_service)],
    as_of: date | None = None,
) -> DigestResponse:
    """Return the (possibly cached) cross-module digest for one day."""
    day = as_of or datetime.now(tz=UTC).date()
    result = await service.digest(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        as_of=day,
        force_refresh=False,
    )
    return _response(result)


@router.post("/digest/refresh", response_model=DigestResponse)
async def refresh_digest(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[NarratorService, Depends(get_narrator_service)],
    as_of: date | None = None,
) -> DigestResponse:
    """Force-recompute today's digest (gated by erp.ai.narrator.refresh upstream)."""
    day = as_of or datetime.now(tz=UTC).date()
    result = await service.digest(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        as_of=day,
        force_refresh=True,
    )
    return _response(result)
