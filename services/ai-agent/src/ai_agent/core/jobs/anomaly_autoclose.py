"""Anomaly auto-close job - dismisses open anomalies after 30 days (spec 4.4).

Runs periodically within the FastAPI lifespan. Any anomaly with
status='open' and created_at older than ANOMALY_AUTO_CLOSE_DAYS is
bulk-updated to status='dismissed' with a system note.

Isolation: anomalies are RLS-guarded by ``tenant_id``, so a single global
UPDATE would touch at most the caller's own tenant (or zero rows when no
context is pinned). The job therefore enumerates active tenants from the
permissive ``tenants_readable`` projection and auto-closes per-tenant, pinning
the ``TenantContext`` (which drives the transaction-local GUC in db/session.py)
before each pass. One tenant's failure never aborts the pass for the others.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.anomaly_repository import AnomalyRepository
from ai_agent.db.repository import TenantRepository
from ai_agent.db.session import async_session_factory

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.jobs.anomaly_autoclose")

# How often to check for stale anomalies (in seconds).
_INTERVAL_SECONDS = 3600  # once per hour


async def run_anomaly_autoclose_job() -> None:
    """Background loop that auto-closes stale open anomalies per tenant."""
    while True:
        try:
            await close_all_tenants()
        except Exception:
            logger.exception("anomaly_autoclose.pass_failed")
        await asyncio.sleep(_INTERVAL_SECONDS)


async def close_all_tenants(
    *,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
    repo_factory: Callable[[AsyncSession], AnomalyRepository] = AnomalyRepository,
) -> int:
    """Auto-close stale anomalies for every active tenant; returns total count.

    Each tenant runs under its own session so ``TenantContext`` is pinned
    before the first query and the transaction-local ``set_config`` scopes the
    UPDATE to that tenant only. A failure for one tenant is logged and the
    pass continues with the rest.
    """
    total = 0
    async with session_factory() as listing_session:
        tenants = await TenantRepository(listing_session).list_active()
    if not tenants:
        logger.debug("anomaly_autoclose.no_active_tenants")
        return 0
    for tenant in tenants:
        try:
            async with session_factory() as session:
                TenantContext.set(str(tenant.id))
                TenantContext.set_tenant_slug(tenant.slug)
                closed = await repo_factory(session).auto_close_stale(
                    close_days=settings.ANOMALY_AUTO_CLOSE_DAYS,
                )
                await session.commit()
                total += closed
                if closed:
                    logger.info(
                        "anomaly_autoclose.tenant_completed",
                        tenant_id=str(tenant.id),
                        closed=closed,
                    )
        except Exception:
            logger.exception("anomaly_autoclose.tenant_failed", tenant_id=str(tenant.id))
    logger.info("anomaly_autoclose.pass_complete", tenants=len(tenants), closed=total)
    return total
