"""Scheduled anomaly detection — per-tenant background scan (spec §4.3).

Detects anomalies every 15 minutes for every active tenant and dispatches the
critical-only admin email introduced in the INV-AI-002 slice. Lives under
``ai_agent.api`` rather than ``core/jobs`` because it orchestrates feature
services (import-linter: foundations must never depend on features).

Authentication: :class:`HttpInventoryGateway` forwards a bearer token + tenant
slug to core. A background task has no user JWT, so the pass authenticates
with a dedicated service token (``AI_ANOMALY_SCAN_SERVICE_TOKEN``). Empty
default disables the scheduled pass (log-only), mirroring the log-only SMTP
transport default; deploying scans means provisioning the matching credential
in core and setting it here.

Isolation: tenant enumeration runs against the permissive ``tenants_readable``
policy with no GUC set, then each tenant's pass opens its OWN session and sets
``TenantContext`` before the first query — the transaction-local
``set_config`` (db/session.py) then scopes every RLS-guarded row. One tenant's
failure never aborts the pass for the others.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.email import build_email_service
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.anomaly_repository import AnomalyRepository
from ai_agent.db.anomaly_rule_stats_repository import AnomalyRuleStatsRepository
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.repository import TenantRepository
from ai_agent.db.session import async_session_factory
from ai_agent.db.settings_repository import SettingsRepository
from ai_agent.features.anomalies.service import AnomalyService
from ai_agent.features.nl_query.gateway import HttpInventoryGateway, InventoryGatewayPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.scheduled.anomaly_scan")

# Spec §4.3: detection runs every 15 minutes.
_INTERVAL_SECONDS = 900


def _build_scan_service(session: AsyncSession, gateway: InventoryGatewayPort) -> AnomalyService:
    """Mirror the router's composition root for one background pass."""

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


async def _scan_tenant(
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    base_url: str,
    service_token: str,
    session_factory: Callable[[], AsyncSession],
    service_factory: Callable[[AsyncSession, InventoryGatewayPort], AnomalyService],
) -> None:
    """Run one detection pass for a tenant under its RLS context."""
    async with session_factory() as session:
        TenantContext.set(str(tenant_id))
        TenantContext.set_tenant_slug(tenant_slug)
        gateway = HttpInventoryGateway(
            base_url=base_url, bearer_token=service_token, tenant_slug=tenant_slug
        )
        service = service_factory(session, gateway)
        report = await service.run_scan(tenant_id=tenant_id)
        await session.commit()
        logger.info(
            "anomaly_scan.tenant_completed",
            tenant_id=str(tenant_id),
            detected=report.detected,
            duplicates_skipped=report.duplicates_skipped,
        )


async def scan_all_tenants(
    *,
    service_token: str,
    base_url: str,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
    service_factory: Callable[
        [AsyncSession, InventoryGatewayPort], AnomalyService
    ] = _build_scan_service,
) -> None:
    """Run one detection pass per active tenant; failures isolated per tenant."""
    if not service_token:
        logger.debug("anomaly_scan.skipped_no_service_token")
        return
    async with session_factory() as listing_session:
        tenants = await TenantRepository(listing_session).list_active()
    if not tenants:
        logger.debug("anomaly_scan.no_active_tenants")
        return
    for tenant in tenants:
        try:
            await _scan_tenant(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                base_url=base_url,
                service_token=service_token,
                session_factory=session_factory,
                service_factory=service_factory,
            )
        except Exception:
            logger.exception("anomaly_scan.tenant_failed", tenant_id=str(tenant.id))


async def run_scheduled_anomaly_scan() -> None:
    """Background loop: one detection pass every 15 minutes (spec §4.3)."""
    while True:
        try:
            await scan_all_tenants(
                service_token=settings.ANOMALY_SCAN_SERVICE_TOKEN,
                base_url=settings.INVENTORY_SERVICE_URL,
            )
        except Exception:
            logger.exception("anomaly_scan.pass_failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
