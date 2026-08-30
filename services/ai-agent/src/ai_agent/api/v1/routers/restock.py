"""/ai/suggestions endpoints - restock suggestions + review (spec §3.5).

Authn here; authz at the core proxy edge (erp.inventory.read to view,
erp.inventory.ai.approve to review/scan - checked before forwarding).
Scan is limited to one run per hour per tenant (spec §5.4).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.routers.nl_query import get_inventory_gateway
from ai_agent.api.v1.schemas.restock import (
    RestockSettingsResponse,
    RestockSettingsUpdate,
    ReviewDecisionRequest,
    ScanResponse,
    SuggestionItem,
    SuggestionListResponse,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.rate_limit import limiter
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.restock_stats_repository import RestockStatsRepository
from ai_agent.db.settings_repository import SettingsRepository
from ai_agent.db.suggestion_repository import SuggestionRepository
from ai_agent.features.nl_query.gateway import InventoryGatewayPort
from ai_agent.features.restock.service import RestockService

router = APIRouter(prefix="/ai/suggestions", tags=["ai-restock"])


def get_restock_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[InventoryGatewayPort, Depends(get_inventory_gateway)],
) -> RestockService:
    """Compose the restock stack for one request."""

    async def gateway_factory() -> InventoryGatewayPort:
        return gateway

    return RestockService(
        gateway_factory=gateway_factory,
        suggestions=SuggestionRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
        settings=SettingsRepository(session),
        stats=RestockStatsRepository(session),
    )


def _to_item(row: Any) -> SuggestionItem:
    return SuggestionItem(
        id=row.id,
        product_id=row.product_id,
        warehouse_id=row.warehouse_id,
        current_stock=row.current_stock,
        reorder_point=row.reorder_point,
        suggested_qty=row.suggested_qty,
        estimated_cost=row.estimated_cost,
        reason=row.reason,
        confidence=row.confidence,
        status=row.status,
        review_note=row.review_note,
        created_at=row.created_at,
    )


@router.get("", response_model=SuggestionListResponse)
async def list_suggestions(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> SuggestionListResponse:
    """Pending restock suggestions for this tenant (newest first)."""
    rows, total = await SuggestionRepository(session).list_by_status(
        tenant_id=user["tenant_id"], status="pending"
    )
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    return SuggestionListResponse(
        data=[_to_item(r) for r in rows],
        meta={"total": total, "pending": total},
    )


@router.post("/scan", response_model=ScanResponse)
async def trigger_scan(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[RestockService, Depends(get_restock_service)],
) -> ScanResponse:
    """Run the deterministic suggestion scan now (spec §3.3 manual trigger)."""
    # Spec §5.4: per-tenant background scans limited to 1/hour.
    await limiter.enforce(
        key=f"ai:restock_scan:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_SCAN_PER_HOUR,
        window_seconds=3600,
    )
    report = await service.run_scan(tenant_id=user["tenant_id"])
    return ScanResponse(
        created=report.created,
        skipped_pending=report.skipped_pending,
        considered=report.considered,
    )


def _to_settings_response(row: Any) -> RestockSettingsResponse:
    return RestockSettingsResponse(
        tenant_id=row.tenant_id,
        lead_time_days=row.lead_time_days,
        safety_factor=row.safety_factor,
        v2_enabled=row.v2_enabled,
        sensitivity=row.sensitivity,
        fp_threshold=row.fp_threshold,
        email_alerts_enabled=row.email_alerts_enabled,
    )


@router.get("/settings", response_model=RestockSettingsResponse)
async def get_settings(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RestockSettingsResponse:
    """The tenant's AI tunables; conservative defaults when no row exists."""
    row = await SettingsRepository(session).get_or_create_default(tenant_id=user["tenant_id"])
    return _to_settings_response(row)


@router.patch("/settings", response_model=RestockSettingsResponse)
async def patch_settings(
    body: RestockSettingsUpdate,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RestockSettingsResponse:
    """Update one or more AI tunables; returns the merged snapshot."""
    row = await SettingsRepository(session).update(
        tenant_id=user["tenant_id"],
        lead_time_days=body.lead_time_days,
        safety_factor=body.safety_factor,
        v2_enabled=body.v2_enabled,
        sensitivity=body.sensitivity,
        fp_threshold=body.fp_threshold,
        email_alerts_enabled=body.email_alerts_enabled,
    )
    return _to_settings_response(row)


@router.post("/{suggestion_id}/approve", response_model=SuggestionItem)
async def approve_suggestion(
    suggestion_id: uuid.UUID,
    body: ReviewDecisionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RestockService, Depends(get_restock_service)],
) -> SuggestionItem:
    """Approve a pending suggestion (spec §3.4: erp.inventory.ai.approve)."""
    await _enforce_review_limit(user)
    await service.review(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        suggestion_id=suggestion_id,
        decision="approved",
        note=body.note,
    )
    row = await SuggestionRepository(session).get_for_review(
        tenant_id=user["tenant_id"], suggestion_id=suggestion_id
    )
    return _to_item(row)


@router.post("/{suggestion_id}/reject", response_model=SuggestionItem)
async def reject_suggestion(
    suggestion_id: uuid.UUID,
    body: ReviewDecisionRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RestockService, Depends(get_restock_service)],
) -> SuggestionItem:
    """Reject a pending suggestion; the note feeds the feedback loop."""
    await _enforce_review_limit(user)
    await service.review(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        suggestion_id=suggestion_id,
        decision="rejected",
        note=body.note,
    )
    row = await SuggestionRepository(session).get_for_review(
        tenant_id=user["tenant_id"], suggestion_id=suggestion_id
    )
    return _to_item(row)


async def _enforce_review_limit(user: dict[str, Any]) -> None:
    """Spec §5.4: 10 approvals/rejections per minute per user."""
    await limiter.enforce(
        key=f"ai:suggestion_review:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_APPROVAL_PER_MIN,
        window_seconds=60,
    )
