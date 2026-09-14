"""Scheduled CRM pipeline anomaly scan - hourly background job (SKY-91).

Every hour, for every active tenant, the scan enumerates all opportunities
via core's paginated CRM API, runs the deterministic anomaly rules on open
deals (activity bursts, missing activity, stage stalls), and persists new
findings into ``ai_crm_anomalies`` with an audit trail. It is the anomaly
twin of the CRM follow-up scan and shares its architectural boundary: it
lives under ``ai_agent.api.scheduled`` because it orchestrates feature
services and depends on the CRM gateway.

Authentication: the scan runs as a system task with no user JWT. It
authenticates with the same dedicated service token the follow-up scan uses
(``CRM_SCAN_SERVICE_TOKEN``) and forwards a per-tenant ``X-Tenant-Slug``.
Empty token disables the scan (log-only).

Isolation: tenant enumeration uses the ``tenants_readable`` policy (no GUC),
then each tenant opens its own session and sets ``TenantContext`` before the
first CRM query - the transaction-local ``set_config`` scopes every RLS
row. One tenant's failure never aborts others.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.repository import TenantRepository
from ai_agent.db.session import async_session_factory
from ai_agent.features.anomalies.crm_scan import CrmAnomalyScanService
from ai_agent.features.crm.gateway import CrmGatewayPort, HttpCrmGateway
from ai_agent.features.crm.repositories import CrmAiRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.scheduled.crm_anomaly_scan")

# Hourly scan (one pass per cycle; stale open anomalies are re-checked on the
# next pass once the previous row is resolved/dismissed).
_INTERVAL_SECONDS = 3600


def _build_scan_service(
    session: AsyncSession,
    gateway: CrmGatewayPort,
) -> CrmAnomalyScanService:
    """Compose the anomaly scan stack for one tenant pass."""
    return CrmAnomalyScanService(
        gateway=gateway,
        repo=CrmAiRepository(session),
        audit=AuditService(AiAuditLogRepository(session)),
    )


async def _scan_tenant(
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    base_url: str,
    service_token: str,
    session_factory: Callable[[], AsyncSession],
    service_factory: Callable[[AsyncSession, CrmGatewayPort], CrmAnomalyScanService],
) -> None:
    """Run one anomaly detection pass for a tenant under its RLS context."""
    async with session_factory() as session:
        TenantContext.set(str(tenant_id))
        TenantContext.set_tenant_slug(tenant_slug)

        gateway = HttpCrmGateway(
            base_url=base_url,
            bearer_token=service_token,
            tenant_slug=tenant_slug,
        )
        service = service_factory(session, gateway)
        report = await service.run_scan(tenant_id=tenant_id)
        await session.commit()
        logger.info(
            "crm_anomaly_scan.tenant_completed",
            tenant_id=str(tenant_id),
            scanned=report.scanned_opportunities,
            detected=report.detected,
            duplicates_skipped=report.duplicates_skipped,
        )


async def scan_all_tenants(
    *,
    service_token: str,
    base_url: str,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
    service_factory: Callable[
        [AsyncSession, CrmGatewayPort], CrmAnomalyScanService
    ] = _build_scan_service,
) -> None:
    """Run one anomaly detection pass per active tenant; failures isolated
    per tenant."""
    if not service_token:
        logger.debug("crm_anomaly_scan.skipped_no_service_token")
        return
    async with session_factory() as listing_session:
        tenants = await TenantRepository(listing_session).list_active()
    if not tenants:
        logger.debug("crm_anomaly_scan.no_active_tenants")
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
            logger.exception(
                "crm_anomaly_scan.tenant_failed",
                tenant_id=str(tenant.id),
            )


async def run_crm_anomaly_scan() -> None:
    """Background loop: one anomaly detection pass every hour."""
    while True:
        try:
            await scan_all_tenants(
                service_token=settings.CRM_SCAN_SERVICE_TOKEN,
                base_url=settings.INVENTORY_SERVICE_URL,
            )
        except Exception:
            logger.exception("crm_anomaly_scan.pass_failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
