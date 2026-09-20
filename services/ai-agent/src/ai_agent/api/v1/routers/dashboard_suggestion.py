"""/ai/dashboards/suggest endpoint - AI-powered layout suggestion (BUG-AI-002).

Authentication happens here; authorization happened upstream at the core
monolith's proxy before forwarding (SKY-57 "AI is a proxy, not a bypass").
This router composes per-request dependencies: caller identity, a telemetry
gateway bound to the CALLER'S token, and the service wired to the shared LLM
router from app.state.

Deployment gate: the endpoint is OFF by default. When
``AI_DASHBOARD_SUGGEST_ENABLED`` is false it answers 501 (not implemented),
so neither the core proxy nor the frontend can mistake a disabled feature for
a real suggestion. The telemetry read is gated by Core's own threshold and the
response always carries an explicit status - never a silent empty 200.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ai_agent.api.deps import get_current_user
from ai_agent.core.config import settings
from ai_agent.core.rate_limit import limiter
from ai_agent.core.tenant_context import TenantContext
from ai_agent.features.dashboard_suggestion.gateway import (
    HttpDashboardGateway,
)
from ai_agent.features.dashboard_suggestion.schemas import (
    SuggestionRequest,
    SuggestionResponse,
    WidgetLayoutItem,
)
from ai_agent.features.dashboard_suggestion.service import DashboardSuggestionService

router = APIRouter(prefix="/ai/dashboards", tags=["ai-dashboards"])


def get_dashboard_gateway(request: Request) -> HttpDashboardGateway:
    """Gateway bound to THIS request's identity - never service credentials.

    Core sees the caller's own JWT and tenant slug, so the telemetry read runs
    with exactly the access the human user already has.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return HttpDashboardGateway(
        base_url=str(settings.REPORT_SERVICE_URL),
        bearer_token=token,
        tenant_slug=TenantContext.get_tenant_slug() or "",
        timeout_seconds=settings.REPORT_SERVICE_TIMEOUT_SECONDS,
    )


def _build_service(request: Request) -> DashboardSuggestionService:
    """Compose the suggestion stack for one request (test-visible seam)."""
    return DashboardSuggestionService(
        llm_router=request.app.state.llm_router,
        gateway=get_dashboard_gateway(request),
    )


def _tenant_id(user: dict[str, Any]) -> uuid.UUID:
    val = user["tenant_id"]
    return uuid.UUID(val) if isinstance(val, str) else val


@router.post("/suggest", response_model=SuggestionResponse)
async def suggest_layout(
    body: SuggestionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    request: Request,
) -> SuggestionResponse:
    """Request an AI-powered layout suggestion based on widget telemetry.

    501 when the feature flag is off; otherwise an explicit-status suggestion
    (``suggested`` / ``insufficient_data`` / ``fallback``).
    """
    if not settings.DASHBOARD_SUGGEST_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Dashboard suggestions are not enabled on this service",
        )

    await limiter.enforce(
        key=f"ai:dashboard_suggest:{user['user_id']}",
        limit=settings.RATE_LIMIT_DASHBOARD_SUGGEST_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )

    service = _build_service(request)
    result = await service.suggest(
        tenant_id=_tenant_id(user),
        current_layout=[item.model_dump() for item in body.current_layout],
    )

    return SuggestionResponse(
        status=result["status"],
        suggested_layout=[WidgetLayoutItem(**item) for item in result["suggested_layout"]],
        reasoning=result["reasoning"],
        confidence=result["confidence"],
    )
