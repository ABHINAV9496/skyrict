"""CRM AI endpoints - lead score badge, deal health badge, follow-up management
(SKY-61), transcript analysis (SKY-91).

Routes mount at ``/api/v1/ai/crm`` and expose the deterministic engines built
in C4-C7 + the transcript analyzer. The gateway is bound to the *caller's* JWT
so core enforces the existing CRM read permissions - the AI service never
bypasses authorization.

Rate limits (C8):
- ``/score``, ``/health`` and ``/opportunities/sweep`` use ``RATE_LIMIT_CRM_PER_MIN`` (15/min/user).
- ``/follow-ups/{id}/apply``, ``/dismiss`` and the transcript POST use ``RATE_LIMIT_CRM_APPLY_PER_MIN`` (10/min/user) - they are write-like and, for the transcript, trigger an LLM call.
- Both enforce the aggregate ``RATE_LIMIT_TENANT_PER_MIN`` (100/min/tenant).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.schemas.crm_ai import (
    CrmAnomalyItem,
    CrmAnomalySeverity,
    CrmAnomalyStatus,
    DealHealthResponse,
    DealHealthSweepResponse,
    FollowUpItem,
    FollowUpSuggestionType,
    HealthBand,
    LeadScoreResponse,
    TranscriptAnalysisResponse,
    TranscriptAnalyzeRequest,
    TranscriptSentiment,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.rate_limit import limiter
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.features.crm.gateway import HttpCrmGateway
from ai_agent.features.crm.repositories import CrmAiRepository
from ai_agent.features.crm.service import CrmAiService
from ai_agent.features.crm.transcript_analysis import TRANSCRIPT_ANALYSIS_VERSION

router = APIRouter(prefix="/ai/crm", tags=["ai-crm"])


def _follow_up_to_item(row: Any) -> FollowUpItem:
    """Map a repository row to the API response schema."""
    return FollowUpItem(
        id=row.id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        suggestion_type=FollowUpSuggestionType(row.suggestion_type),
        draft_content=row.draft_content,
        reasoning=row.reasoning,
        confidence=row.confidence,
        status=row.status,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def _get_crm_gateway(request: Request) -> HttpCrmGateway:
    """CRM gateway bound to THIS request's identity - never service credentials."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    return HttpCrmGateway(
        base_url=str(settings.INVENTORY_SERVICE_URL),
        bearer_token=token,
        tenant_slug=TenantContext.get_tenant_slug() or "",
    )


def _build_service(request: Request, session: AsyncSession) -> CrmAiService:
    """Compose the CRM AI stack for one request."""
    return CrmAiService(
        gateway=_get_crm_gateway(request),
        repo=CrmAiRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
        llm_router=getattr(request.app.state, "llm_router", None),
    )


def get_crm_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> CrmAiService:
    """FastAPI dependency wrapping :func:`_build_service`."""
    return _build_service(request, session)


# ---------------------------------------------------------------------------
# Lead score
# ---------------------------------------------------------------------------


@router.post(
    "/leads/{lead_id}/score",
    response_model=LeadScoreResponse,
)
async def score_lead(
    lead_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> LeadScoreResponse:
    """Compute and persist a deterministic AI score for the given lead."""
    await limiter.enforce(
        key=f"ai:crm:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    result = await service.compute_lead_score(
        tenant_id=user["tenant_id"],
        lead_id=lead_id,
        user_id=user["user_id"],
    )
    return LeadScoreResponse(
        lead_id=lead_id,
        score=result.score,
        confidence=result.confidence,
        factors=result.factors,
        model_version="v1",
        computed_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Deal health
# ---------------------------------------------------------------------------


@router.get(
    "/opportunities/{opportunity_id}/health",
    response_model=DealHealthResponse,
)
async def get_deal_health(
    opportunity_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> DealHealthResponse:
    """Compute and persist a deterministic health assessment for the given opportunity."""
    await limiter.enforce(
        key=f"ai:crm:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    result = await service.compute_deal_health(
        tenant_id=user["tenant_id"],
        opportunity_id=opportunity_id,
        user_id=user["user_id"],
    )
    return DealHealthResponse(
        opportunity_id=opportunity_id,
        health=HealthBand(result.health),
        confidence=result.confidence,
        risk_factors=result.risk_factors,
        recommended_actions=result.recommended_actions,
        engagement_velocity=result.engagement_velocity,
        days_in_stage=result.days_in_stage,
        computed_at=datetime.now(UTC),
    )


@router.post(
    "/opportunities/sweep",
    response_model=DealHealthSweepResponse,
)
async def sweep_deal_health(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> DealHealthSweepResponse:
    """Recheck + persist deal health for every open opportunity closing within
    the next 12 months (the manual twin of the scheduled nightly sweep)."""
    await limiter.enforce(
        key=f"ai:crm:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    result = await service.sweep_deal_health(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    return DealHealthSweepResponse(
        assessed=result.assessed,
        healthy=result.healthy,
        at_risk=result.at_risk,
        critical=result.critical,
    )


# ---------------------------------------------------------------------------
# Transcript analysis (SKY-91)
# ---------------------------------------------------------------------------


@router.post(
    "/activities/{activity_id}/transcript",
    response_model=TranscriptAnalysisResponse,
)
async def analyze_activity_transcript(
    activity_id: uuid.UUID,
    body: TranscriptAnalyzeRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> TranscriptAnalysisResponse:
    """Analyze a CRM call/meeting transcript and persist the interpretation.

    The core proxy already wrote the raw transcript into
    ``erp_crm_activities.transcript_text`` (scoped CRM write) before
    forwarding here - this endpoint only produces and stores the AI
    interpretation. AI is a proxy, not an auth bypass: the caller's JWT was
    validated upstream with ``erp.ai.invoke`` + ``erp.crm.write`` and is
    re-verified against the relayed tenant slug.
    """
    await limiter.enforce(
        key=f"ai:crm_apply:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_APPLY_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    result = await service.analyze_transcript(
        tenant_id=user["tenant_id"],
        activity_id=activity_id,
        user_id=user["user_id"],
        transcript=body.transcript,
    )
    return TranscriptAnalysisResponse(
        activity_id=activity_id,
        summary=result.summary,
        objection_score=result.objection_score,
        objections=result.objections,
        next_best_action=result.next_best_action,
        sentiment=TranscriptSentiment(result.sentiment),
        key_topics=result.key_topics,
        confidence=result.confidence,
        model_version=TRANSCRIPT_ANALYSIS_VERSION,
        analyzed_at=datetime.now(UTC),
    )


@router.get(
    "/activities/{activity_id}/transcript",
    response_model=TranscriptAnalysisResponse,
)
async def get_activity_transcript_analysis(
    activity_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> TranscriptAnalysisResponse:
    """Latest persisted transcript analysis for an activity (404 if none yet)."""
    await limiter.enforce(
        key=f"ai:crm:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    row = await service.latest_transcript_analysis(
        tenant_id=user["tenant_id"],
        activity_id=activity_id,
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No transcript analysis found for this activity",
        )
    return TranscriptAnalysisResponse(
        activity_id=row.activity_id,
        summary=row.summary,
        objection_score=row.objection_score,
        objections=list(row.objections),
        next_best_action=row.next_best_action,
        sentiment=TranscriptSentiment(row.sentiment),
        key_topics=list(row.key_topics),
        confidence=row.confidence,
        model_version=row.model_version,
        analyzed_at=row.analyzed_at,
    )


# ---------------------------------------------------------------------------
# Follow-up management
# ---------------------------------------------------------------------------


@router.get("/follow-ups", response_model=list[FollowUpItem])
async def list_follow_ups(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> list[FollowUpItem]:
    """List pending follow-up suggestions for the authenticated user."""
    await limiter.enforce(
        key=f"ai:crm:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_PER_MIN,
        window_seconds=60,
    )
    rows = await service.list_pending_follow_ups(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    return [_follow_up_to_item(row) for row in rows]


@router.post("/follow-ups/{suggestion_id}/apply", response_model=FollowUpItem)
async def apply_follow_up(
    suggestion_id: uuid.UUID,
    body: dict[str, Any],
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> FollowUpItem:
    """Apply a pending follow-up suggestion (one-click send).

    The request body must contain ``activity_id`` - the UUID of the CRM
    activity created in core by the caller.
    """
    await limiter.enforce(
        key=f"ai:crm_apply:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_APPLY_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    activity_id_raw = body.get("activity_id")
    if activity_id_raw is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="activity_id is required")
    activity_id = uuid.UUID(str(activity_id_raw))

    row = await service.apply_follow_up(
        tenant_id=user["tenant_id"],
        suggestion_id=suggestion_id,
        user_id=user["user_id"],
        activity_id=activity_id,
    )
    return _follow_up_to_item(row)


@router.post("/follow-ups/{suggestion_id}/dismiss", response_model=FollowUpItem)
async def dismiss_follow_up(
    suggestion_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> FollowUpItem:
    """Dismiss a pending follow-up suggestion."""
    await limiter.enforce(
        key=f"ai:crm_apply:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_APPLY_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    row = await service.dismiss_follow_up(
        tenant_id=user["tenant_id"],
        suggestion_id=suggestion_id,
        user_id=user["user_id"],
    )
    return _follow_up_to_item(row)


# ---------------------------------------------------------------------------
# CRM anomaly management (SKY-91)
# ---------------------------------------------------------------------------


@router.get("/anomalies", response_model=list[CrmAnomalyItem])
async def list_crm_anomalies(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> list[CrmAnomalyItem]:
    """List all open CRM pipeline anomalies for the tenant (newest first).

    The scan materializes anomalies on a schedule or on demand; this feed is
    the tenant-scoped inbox that the opportunities page anchor-panel renders.
    """
    await limiter.enforce(
        key=f"ai:crm:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    rows = await service.list_open_crm_anomalies(tenant_id=user["tenant_id"])
    return [_crm_anomaly_to_item(row) for row in rows]


@router.post("/anomalies/{anomaly_id}/resolve", response_model=CrmAnomalyItem)
async def resolve_crm_anomaly(
    anomaly_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> CrmAnomalyItem:
    """Resolve an open CRM anomaly (the rep acted on it)."""
    await limiter.enforce(
        key=f"ai:crm_apply:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_APPLY_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    try:
        row = await service.resolve_crm_anomaly(
            tenant_id=user["tenant_id"],
            anomaly_id=anomaly_id,
            user_id=user["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _crm_anomaly_to_item(row)


@router.post("/anomalies/{anomaly_id}/dismiss", response_model=CrmAnomalyItem)
async def dismiss_crm_anomaly(
    anomaly_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[CrmAiService, Depends(get_crm_service)],
) -> CrmAnomalyItem:
    """Dismiss an open CRM anomaly as a false positive."""
    await limiter.enforce(
        key=f"ai:crm_apply:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_CRM_APPLY_PER_MIN,
        window_seconds=60,
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    try:
        row = await service.dismiss_crm_anomaly(
            tenant_id=user["tenant_id"],
            anomaly_id=anomaly_id,
            user_id=user["user_id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _crm_anomaly_to_item(row)


def _crm_anomaly_to_item(row: Any) -> CrmAnomalyItem:
    """Map a repository row to the API response schema."""
    return CrmAnomalyItem(
        id=row.id,
        opportunity_id=row.opportunity_id,
        rule_id=row.rule_id,
        severity=CrmAnomalySeverity(row.severity),
        status=CrmAnomalyStatus(row.status),
        title=row.title,
        description=row.description,
        context=dict(row.context or {}),
        detected_at=row.detected_at,
    )
