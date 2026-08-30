"""Tenant lookup against the shared identity ``tenants`` table.

Only the middleware resolves tenants, and it delegates here. The repository
lives outside the api layer so api code never imports ORM models directly.
``tenants`` has a permissive SELECT policy (``tenants_readable``, created by
identity's migration 0001) so lookup succeeds before any request tenant
context exists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from ai_agent.models import TenantModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TenantRepository:
    """Read-only access to the shared tenants table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_slug(self, slug: str) -> TenantModel | None:
        """Return the tenant with the given slug, or None."""
        result = await self.session.execute(select(TenantModel).where(TenantModel.slug == slug))
        return result.scalar_one_or_none()

    async def list_active(self) -> list[TenantModel]:
        """Return every active tenant, oldest first.

        Used by the scheduled anomaly scan to iterate tenants without a request
        context; ``tenants`` carries the permissive ``tenants_readable`` policy
        so this enumeration succeeds before any GUC is set.
        """
        result = await self.session.execute(
            select(TenantModel)
            .where(TenantModel.is_active.is_(True))
            .order_by(TenantModel.created_at)
        )
        return list(result.scalars().all())
