"""TTL sweep runner — composition root for ``ai-agent sweep-caches``.

Expired ``ai_query_cache`` rows are purged from every tenant. The table is
covered by row-level security (``tenant_id = current_tenant_id()``), so a
single global DELETE would match ZERO rows: the policy hides every row when no
tenant context is pinned. The sweep therefore enumerates tenants from the
shared, non-RLS ``tenants`` projection and deletes per-tenant, pinning the RLS
context before each DELETE. A failure for one tenant aborts the whole sweep so
an operator notices instead of silently under-deleting.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from ai_agent.core.tenant_context import TenantContext
from ai_agent.db.query_cache_repository import QueryCacheRepository
from ai_agent.db.session import async_session_factory
from ai_agent.models.tenant import TenantModel

logger = structlog.get_logger("ai_agent.rag.sweep")


async def sweep_expired_query_cache() -> int:
    """Delete every tenant's expired ai_query_cache rows; returns total count."""
    total = 0
    async with async_session_factory() as session:
        result = await session.execute(select(TenantModel.id))
        tenant_ids = [row[0] for row in result.all()]
        for tenant_id in tenant_ids:
            TenantContext.set(str(tenant_id))
            TenantContext.set_tenant_slug(None)
            deleted = await QueryCacheRepository(session).delete_expired()
            total += deleted
            if deleted:
                logger.info(
                    "rag.sweep_tenant",
                    tenant_id=str(tenant_id),
                    deleted=deleted,
                )
        await session.commit()
    logger.info("rag.sweep_complete", shared_tenants=len(tenant_ids), deleted=total)
    return total
