"""Tenant repository — DB operations for the tenants table.

All SQLAlchemy stays in this file. Service-facing methods accept and return
domain entities (``identity.domain.entities.Tenant``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from identity.core.exceptions import TenantNotFoundError
from identity.db.repository import SqlRepository
from identity.domain.entities import Tenant
from identity.models.tenant import TenantModel


def _to_orm(tenant: Tenant) -> TenantModel:
    """Map a domain entity to a new ORM model (id is DB-generated unless set)."""
    model_kwargs: dict[str, Any] = {
        "name": tenant.name,
        "slug": tenant.slug,
        "plan_tier": tenant.plan_tier,
        "is_active": tenant.is_active,
        "mfa_required_for_all_members": tenant.mfa_required_for_all_members,
    }
    if tenant.id is not None:
        model_kwargs["id"] = tenant.id
    return TenantModel(**model_kwargs)


def _from_orm(model: TenantModel) -> Tenant:
    """Map an ORM model to a domain entity."""
    return Tenant(
        id=model.id,
        name=model.name,
        slug=model.slug,
        is_active=model.is_active,
        plan_tier=model.plan_tier,
        mfa_required_for_all_members=model.mfa_required_for_all_members,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class TenantRepository(SqlRepository):
    """Repository for tenant persistence (implements ``TenantRepositoryPort``)."""

    async def get_by_id(self, tenant_id: str | uuid.UUID) -> Tenant | None:
        """Fetch a tenant by primary key, or None when absent."""
        model = await self.session.get(TenantModel, tenant_id)
        return _from_orm(model) if model is not None else None

    async def get_by_slug(self, slug: str) -> Tenant | None:
        """Fetch a tenant by slug."""
        stmt = select(TenantModel).where(TenantModel.slug == slug)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def slug_exists(self, slug: str) -> bool:
        """Check if a tenant with this slug already exists."""
        tenant = await self.get_by_slug(slug)
        return tenant is not None

    async def create(self, tenant: Tenant) -> Tenant:
        """Persist a new tenant and return it with its DB-generated id."""
        model = _to_orm(tenant)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def update_settings(
        self, tenant_id: str | uuid.UUID, *, mfa_required_for_all_members: bool
    ) -> Tenant:
        """Update tenant security settings and flush."""
        model = await self.session.get(TenantModel, tenant_id)
        if model is None:
            raise TenantNotFoundError("Organization not found")
        model.mfa_required_for_all_members = mfa_required_for_all_members
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)
