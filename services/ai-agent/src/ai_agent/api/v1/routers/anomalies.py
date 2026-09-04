"""/ai/anomalies endpoints - detection feed + review (spec §4.6).

Authn here; authz at the core proxy edge (erp.inventory.read to view,
erp.inventory.write to review - checked before forwarding).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.api.v1.routers.nl_query import get_inventory_gateway
from ai_agent.api.v1.schemas.anomalies import (
    AnomalyItem,
    AnomalyListResponse,
    AnomalyReviewRequest,
    DetectionScanResponse,
)
from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.email import build_email_service
from ai_agent.core.rate_limit import limiter
from ai_agent.db.anomaly_repository import AnomalyRepository
from ai_agent.db.anomaly_rule_stats_repository import AnomalyRuleStatsRepository
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.settings_repository import SettingsRepository
from ai_agent.features.anomalies.service import AnomalyService
from ai_agent.features.nl_query.gateway import InventoryGatewayPort

router = APIRouter(prefix="/ai/anomalies", tags=["ai-anomalies"])


def get_anomaly_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[InventoryGatewayPort, Depends(get_inventory_gateway)],
) -> AnomalyService:
    """Compose the anomaly stack for one request.

    The email transport and per-tenant alert gate are built here (composition
    root) so the service layer stays free of DB and config concerns. No SMTP
    relay and/or no configured recipients means no transport - scans stay
    silent and skip the settings lookup entirely.
    """

    async def gateway_factory() -> InventoryGatewayPort:
        return gateway

    email = None
    notify_addresses: tuple[str, ...] = ()
    notify_enabled = None
    if settings.anomaly_notify_emails:
        email = build_email_service(
            host=settings.EMAIL_SMTP_HOST,
            port=settings.EMAIL_SMTP_PORT,
            from_addr=settings.EMAIL_FROM_ADDR,
            username=settings.EMAIL_SMTP_USERNAME,
            password=settings.EMAIL_SMTP_PASSWORD,
            use_tls=settings.EMAIL_SMTP_USE_TLS,
        )
        notify_addresses = tuple(settings.anomaly_notify_emails)
        settings_repo = SettingsRepository(session)

        async def notify_enabled(tenant_id: uuid.UUID) -> bool:
            row = await settings_repo.get(tenant_id=tenant_id)
            return row.email_alerts_enabled if row else False

    return AnomalyService(
        gateway_factory=gateway_factory,
        anomalies=AnomalyRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
        email=email,
        notify_addresses=notify_addresses,
        notify_enabled=notify_enabled,
        review_base_url=settings.ANOMALY_REVIEW_BASE_URL,
        rule_stats=AnomalyRuleStatsRepository(session),
    )


def _to_item(row: Any) -> AnomalyItem:
    return AnomalyItem(
        id=row.id,
        anomaly_type=row.anomaly_type,
        severity=row.severity,
        title=row.title,
        description=row.description,
        affected_product_id=row.affected_product_id,
        affected_warehouse_id=row.affected_warehouse_id,
        related_movement_ids=list(row.related_movement_ids or []),
        status=row.status,
        resolution_note=row.resolution_note,
        created_at=row.created_at,
    )


@router.get("", response_model=AnomalyListResponse)
async def list_anomalies(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    status: Annotated[str | None, Query()] = None,
) -> AnomalyListResponse:
    """Anomaly feed for this tenant with meta counts."""
    await limiter.enforce(
        key=f"ai:tenant_total:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_TENANT_PER_MIN,
        window_seconds=60,
    )
    rows, meta = await AnomalyRepository(session).list_all(
        tenant_id=user["tenant_id"], status=status
    )
    return AnomalyListResponse(data=[_to_item(r) for r in rows], meta=meta)


@router.post("/scan", response_model=DetectionScanResponse)
async def trigger_scan(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[AnomalyService, Depends(get_anomaly_service)],
) -> DetectionScanResponse:
    """Run detection over the recent movement window now."""
    await limiter.enforce(
        key=f"ai:anomaly_scan:{user['tenant_id']}",
        limit=settings.RATE_LIMIT_SCAN_PER_HOUR,
        window_seconds=3600,
    )
    report = await service.run_scan(tenant_id=user["tenant_id"])
    return DetectionScanResponse(
        detected=report.detected, duplicates_skipped=report.duplicates_skipped
    )


async def _enforce_review_limit(user: dict[str, Any]) -> None:
    """Spec §5.4: 10 anomaly reviews per minute per user."""
    await limiter.enforce(
        key=f"ai:anomaly_review:{user['tenant_id']}:{user['user_id']}",
        limit=settings.RATE_LIMIT_ANOMALY_REVIEW_PER_MIN,
        window_seconds=60,
    )


@router.post("/{anomaly_id}/resolve", response_model=AnomalyItem)
async def resolve_anomaly(
    anomaly_id: uuid.UUID,
    body: AnomalyReviewRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[AnomalyService, Depends(get_anomaly_service)],
) -> AnomalyItem:
    """Mark an open anomaly resolved (erp.inventory.write at the edge)."""
    await _enforce_review_limit(user)
    await service.review(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        anomaly_id=anomaly_id,
        decision="resolved",
        note=body.note,
    )
    row = await AnomalyRepository(session).get(tenant_id=user["tenant_id"], anomaly_id=anomaly_id)
    return _to_item(row)


@router.post("/{anomaly_id}/dismiss", response_model=AnomalyItem)
async def dismiss_anomaly(
    anomaly_id: uuid.UUID,
    body: AnomalyReviewRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[AnomalyService, Depends(get_anomaly_service)],
) -> AnomalyItem:
    """Mark an open anomaly as a false positive (feeds tuning)."""
    await _enforce_review_limit(user)
    await service.review(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        anomaly_id=anomaly_id,
        decision="dismissed",
        note=body.note,
    )
    row = await AnomalyRepository(session).get(tenant_id=user["tenant_id"], anomaly_id=anomaly_id)
    return _to_item(row)


@router.post("/{anomaly_id}/escalate", response_model=AnomalyItem)
async def escalate_anomaly(
    anomaly_id: uuid.UUID,
    body: AnomalyReviewRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[AnomalyService, Depends(get_anomaly_service)],
) -> AnomalyItem:
    """Escalate to admin (open/resolved -> escalated)."""
    await _enforce_review_limit(user)
    await service.review(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        anomaly_id=anomaly_id,
        decision="escalated",
        note=body.note,
    )
    row = await AnomalyRepository(session).get(tenant_id=user["tenant_id"], anomaly_id=anomaly_id)
    return _to_item(row)
