"""TTL sweep runner - composition root for ``core sweep-report-cache``.

Expired ``erp_report_cache`` rows are purged from every tenant. The table is
covered by row-level security (``tenant_id = public.current_tenant_id()``), so
a single global DELETE would match ZERO rows when no tenant context is pinned.
This sweep therefore enumerates tenants from the shared ``tenants`` projection
and deletes per-tenant, pinning the RLS context before each DELETE. A failure
for one tenant aborts the whole sweep so an operator notices instead of
silently under-deleting.
"""

from __future__ import annotations

from sqlalchemy import select

from core.core.logging import get_logger
from core.core.tenant_context import TenantContext
from core.db.session import async_session_factory
from core.features.finance.report_cache import ReportCacheRepository
from core.models.tenant import TenantModel

logger = get_logger("core.finance.report_cache_sweep")


async def sweep_expired_report_cache() -> int:
    """Delete every tenant's expired erp_report_cache rows; returns total count."""
    total = 0
    async with async_session_factory() as session:
        result = await session.execute(select(TenantModel.id))
        tenant_ids = [row[0] for row in result.all()]
        for tenant_id in tenant_ids:
            TenantContext.set(str(tenant_id))
            TenantContext.set_tenant_slug(None)
            deleted = await ReportCacheRepository(session).delete_expired()
            total += deleted
            if deleted:
                logger.info("report_cache.sweep_tenant", tenant_id=str(tenant_id), deleted=deleted)
        await session.commit()
    logger.info("report_cache.sweep_complete", shared_tenants=len(tenant_ids), deleted=total)
    return total
