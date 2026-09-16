"""Suggestion expiry job - auto-expires pending restock suggestions (spec 3.4).

Runs periodically within the FastAPI lifespan. Any suggestion with
status='pending' and created_at older than SUGGESTION_EXPIRY_DAYS is
bulk-updated to status='expired'.

Isolation: suggestions are RLS-guarded by ``tenant_id``, so a single global
UPDATE would match at most the caller's own tenant (or zero rows when no
context is pinned). The job therefore enumerates active tenants from the
permissive ``tenants_readable`` projection and expires per-tenant, pinning the
``TenantContext`` (which drives the transaction-local GUC in db/session.py)
before each pass. One tenant's failure never aborts the pass for the others.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.config import settings
from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.repository import TenantRepository
from ai_agent.db.session import async_session_factory
from ai_agent.db.suggestion_repository import SuggestionRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.jobs.suggestion_expiry")

# How often to check for stale suggestions (in seconds).
_INTERVAL_SECONDS = 3600  # once per hour


async def run_suggestion_expiry_job() -> None:
    """Background loop that expires stale pending suggestions per tenant."""
    while True:
        try:
            await expire_all_tenants()
        except Exception:
            logger.exception("suggestion_expiry.pass_failed")
        await asyncio.sleep(_INTERVAL_SECONDS)


async def expire_all_tenants(
    *,
    session_factory: Callable[[], AsyncSession] = async_session_factory,
    repo_factory: Callable[[AsyncSession], SuggestionRepository] = SuggestionRepository,
) -> int:
    """Expire stale suggestions for every active tenant; returns total count.

    Each tenant runs under its own session so ``TenantContext`` is pinned
    before the first query and the transaction-local ``set_config`` scopes the
    UPDATE to that tenant only. A failure for one tenant is logged and the
    pass continues with the rest.
    """
    total = 0
    async with session_factory() as listing_session:
        tenants = await TenantRepository(listing_session).list_active()
    if not tenants:
        logger.debug("suggestion_expiry.no_active_tenants")
        return 0
    for tenant in tenants:
        try:
            async with session_factory() as session:
                TenantContext.set(str(tenant.id))
                TenantContext.set_tenant_slug(tenant.slug)
                expired = await repo_factory(session).expire_stale(
                    expiry_days=settings.SUGGESTION_EXPIRY_DAYS,
                )
                await session.commit()
                total += expired
                if expired:
                    logger.info(
                        "suggestion_expiry.tenant_completed",
                        tenant_id=str(tenant.id),
                        expired=expired,
                    )
        except Exception:
            logger.exception("suggestion_expiry.tenant_failed", tenant_id=str(tenant.id))
    logger.info("suggestion_expiry.pass_complete", tenants=len(tenants), expired=total)
    return total
