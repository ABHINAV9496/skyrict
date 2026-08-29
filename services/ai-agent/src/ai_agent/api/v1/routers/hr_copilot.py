"""/ai/hr/copilot endpoints - the HR Copilot agent (spec §9, feature 5).

Authentication happens here (JWT re-verification); authorization happened
upstream at the core monolith's proxy (``erp.ai.invoke`` + ``erp.hr.ai.copilot``
checked before forwarding — the "AI is a proxy, not a bypass" rule). This
router composes per-request dependencies: caller identity, an HR gateway bound
to the CALLER'S token, and the engine wired to the shared LLM router from
``app.state``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.features.hr_copilot.engine import HrCopilotEngine
from ai_agent.features.hr_copilot.gateway import HrGatewayPort, HttpHrGateway
from ai_agent.features.hr_copilot.schemas import HrCopilotRequest, HrCopilotResponse
from ai_agent.features.hr_copilot.service import HrCopilotService

router = APIRouter(prefix="/ai/hr/copilot", tags=["ai-hr-copilot"])


def get_hr_gateway(request: Request) -> HrGatewayPort:
    """Gateway bound to THIS request's identity - never service credentials.

    Core sees the caller's own JWT and tenant slug, so every aggregate HR read
    runs with exactly the access the human user already has.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return HttpHrGateway(
        base_url=str(settings.INVENTORY_SERVICE_URL),
        bearer_token=token,
        # Middleware guarantees the slug exists on business routes.
        tenant_slug=TenantContext.get_tenant_slug() or "",
    )


def _build_service(
    request: Request,
    session: AsyncSession,
) -> HrCopilotService:
    """Compose the Copilot stack for one request (test-visible seam)."""
    gateway = get_hr_gateway(request)
    engine = HrCopilotEngine(
        llm_router=request.app.state.llm_router,
        gateway_factory=gateway,
    )
    return HrCopilotService(
        engine=engine,
        audit=AuditService(AiAuditLogRepository(session)),
        rate_limit_per_minute=settings.RATE_LIMIT_HR_COPILOT_PER_MIN,
        tenant_limit_per_minute=settings.RATE_LIMIT_TENANT_PER_MIN,
    )


def get_hr_copilot_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> HrCopilotService:
    """FastAPI dependency wrapping :func:`_build_service`."""
    return _build_service(request, session)


@router.post("/chat", response_model=HrCopilotResponse)
async def copilot_chat(
    body: HrCopilotRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[HrCopilotService, Depends(get_hr_copilot_service)],
) -> HrCopilotResponse:
    """Draft an answer to one HR question grounded in aggregate data + policy."""
    result = await service.ask(
        message=body.message,
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    return HrCopilotResponse(
        answer=result.answer,
        model_used=result.model_used,
        latency_ms=result.latency_ms,
    )
