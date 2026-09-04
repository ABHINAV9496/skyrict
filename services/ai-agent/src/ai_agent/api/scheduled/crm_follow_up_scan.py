"""Scheduled CRM follow-up scan - hourly background job (SKY-61 Part 11).

Every hour, for every active tenant, the scan enumerates all leads and
opportunities via core's paginated CRM API, checks for staleness, and
generates deterministic follow-up suggestions for entity owners.

Lives under ``ai_agent.api.scheduled`` (not ``core/jobs``) because it
orchestrates feature services and depends on the CRM gateway - the same
architectural boundary that places the anomaly scan here.

Authentication: the scan runs as a system task with no user JWT. It
authenticates with a dedicated service token (``CRM_SCAN_SERVICE_TOKEN``)
and forwards a per-tenant ``X-Tenant-Slug``. Empty token disables the
scan (log-only), mirroring the anomaly scan's pattern.

Isolation: tenant enumeration uses the ``tenants_readable`` policy (no GUC),
then each tenant opens its own session and sets ``TenantContext`` before the
first CRM query - the transaction-local ``set_config`` scopes every RLS
row. One tenant's failure never aborts others.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.audit_service import AuditService
from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.audit_repository import AiAuditLogRepository
from ai_agent.db.repository import TenantRepository
from ai_agent.db.session import async_session_factory
from ai_agent.features.crm.follow_up import generate_follow_up
from ai_agent.features.crm.gateway import HttpCrmGateway
from ai_agent.features.crm.repositories import CrmAiRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.scheduled.crm_follow_up_scan")

# Hourly scan (one pass per cycle).
_INTERVAL_SECONDS = 3600

# Maximum number of pending follow-ups per entity to avoid duplicates.
_MAX_PENDING_PER_ENTITY = 1

# Generate suggestions for at most this many entities per tenant per scan to
# avoid overwhelming owners.
_MAX_SUGGESTIONS_PER_SCAN = 50


async def _scan_tenant(
    *,
    tenant_id: uuid.UUID,
    tenant_slug: str,
    base_url: str,
    service_token: str,
    session_factory: Callable[[], AsyncSession],
    stale_days: int,
) -> None:
    """Run one follow-up generation pass for a tenant under its RLS context."""
    async with session_factory() as session:
        TenantContext.set(str(tenant_id))
        TenantContext.set_tenant_slug(tenant_slug)

        gateway = HttpCrmGateway(
            base_url=base_url,
            bearer_token=service_token,
            tenant_slug=tenant_slug,
        )
        repo = CrmAiRepository(session)
        audit = AuditService(AiAuditLogRepository(session))

        now = datetime.now(UTC)
        generated = 0

        # Enumerate leads via paginated core list endpoint.
        leads = await gateway.list_leads()
        for lead in leads:
            if generated >= _MAX_SUGGESTIONS_PER_SCAN:
                break
            if not lead.owner_id:
                continue
            pending = await repo.pending_count_for_entity(
                tenant_id=tenant_id,
                entity_type="lead",
                entity_id=lead.id,
            )
            if pending >= _MAX_PENDING_PER_ENTITY:
                continue
            activities = await gateway.list_activities_for_entity(
                entity_type="lead", entity_id=lead.id
            )
            draft = generate_follow_up(
                entity_type="lead",
                entity=lead,
                activities=activities,
                now=now,
            )
            if draft is None:
                continue
            await repo.create_follow_up_suggestion(
                tenant_id=tenant_id,
                entity_type=draft.entity_type,
                entity_id=draft.entity_id,
                user_id=draft.user_id,
                suggestion_type=draft.suggestion_type,
                draft_content=draft.draft_content,
                reasoning=draft.reasoning,
                confidence=draft.confidence,
                stale_days=stale_days,
            )
            await audit.log(
                action="ai.crm.follow_up.generated",
                tenant_id=tenant_id,
                user_id=draft.user_id,
                input_payload={"entity_type": "lead", "entity_id": str(lead.id)},
                output_payload={
                    "suggestion_type": draft.suggestion_type,
                    "confidence": draft.confidence,
                },
            )
            generated += 1

        # Enumerate opportunities via paginated core list endpoint.
        opportunities = await gateway.list_opportunities()
        for opp in opportunities:
            if generated >= _MAX_SUGGESTIONS_PER_SCAN:
                break
            if not opp.owner_id:
                continue
            pending = await repo.pending_count_for_entity(
                tenant_id=tenant_id,
                entity_type="opportunity",
                entity_id=opp.id,
            )
            if pending >= _MAX_PENDING_PER_ENTITY:
                continue
            activities = await gateway.list_activities_for_entity(
                entity_type="opportunity", entity_id=opp.id
            )
            draft = generate_follow_up(
                entity_type="opportunity",
                entity=opp,
                activities=activities,
                now=now,
            )
            if draft is None:
                continue
            await repo.create_follow_up_suggestion(
                tenant_id=tenant_id,
                entity_type=draft.entity_type,
                entity_id=draft.entity_id,
                user_id=draft.user_id,
                suggestion_type=draft.suggestion_type,
                draft_content=draft.draft_content,
                reasoning=draft.reasoning,
                confidence=draft.confidence,
                stale_days=stale_days,
            )
            await audit.log(
                action="ai.crm.follow_up.generated",
                tenant_id=tenant_id,
                user_id=draft.user_id,
                input_payload={"entity_type": "opportunity", "entity_id": str(opp.id)},
                output_payload={
                    "suggestion_type": draft.suggestion_type,
                    "confidence": draft.confidence,
                },
            )
            generated += 1

        await session.commit()
        logger.info(
            "crm_follow_up_scan.tenant_completed",
            tenant_id=str(tenant_id),
            generated=generated,
        )


async def scan_all_tenants(
    *,
    service_token: str,
    base_url: str,
    stale_days: int,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
) -> None:
    """Run one follow-up pass per active tenant; failures isolated per tenant."""
    if not service_token:
        logger.debug("crm_follow_up_scan.skipped_no_service_token")
        return
    async with session_factory() as listing_session:
        tenants = await TenantRepository(listing_session).list_active()
    if not tenants:
        logger.debug("crm_follow_up_scan.no_active_tenants")
        return
    for tenant in tenants:
        try:
            await _scan_tenant(
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                base_url=base_url,
                service_token=service_token,
                session_factory=session_factory,
                stale_days=stale_days,
            )
        except Exception:
            logger.exception(
                "crm_follow_up_scan.tenant_failed",
                tenant_id=str(tenant.id),
            )


async def run_crm_follow_up_scan() -> None:
    """Background loop: one follow-up generation pass every hour."""
    while True:
        try:
            await scan_all_tenants(
                service_token=settings.CRM_SCAN_SERVICE_TOKEN,
                base_url=settings.INVENTORY_SERVICE_URL,
                stale_days=settings.CRM_SCAN_STALE_DAYS,
            )
        except Exception:
            logger.exception("crm_follow_up_scan.pass_failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
