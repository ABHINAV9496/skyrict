"""Tenant repository - DB operations for the tenants table.

All SQLAlchemy stays in this file. Service-facing methods accept and return
domain entities (``identity.domain.entities.Tenant``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from identity.db.repository import SqlRepository
from identity.domain.entities import Tenant
from identity.models.tenant import TenantModel
from skyrict_common.exceptions import TenantNotFoundError


def _to_orm(tenant: Tenant) -> TenantModel:
    """Map a domain entity to a new ORM model (id is DB-generated unless set)."""
    model_kwargs: dict[str, Any] = {
        "name": tenant.name,
        "slug": tenant.slug,
        "plan_tier": tenant.plan_tier,
        "is_active": tenant.is_active,
        "industry": tenant.industry,
        "billing_address": tenant.billing_address,
        "onboarding_completed_at": tenant.onboarding_completed_at,
        "trial_ends_at": tenant.trial_ends_at,
        "subscription_status": tenant.subscription_status,
        "stripe_customer_id": tenant.stripe_customer_id,
        "stripe_subscription_id": tenant.stripe_subscription_id,
        "billing_email": tenant.billing_email,
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
        industry=model.industry,
        billing_address=model.billing_address,
        onboarding_completed_at=model.onboarding_completed_at,
        trial_ends_at=model.trial_ends_at,
        subscription_status=model.subscription_status,
        stripe_customer_id=model.stripe_customer_id,
        stripe_subscription_id=model.stripe_subscription_id,
        billing_email=model.billing_email,
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

    async def update_billing(
        self,
        tenant_id: str | uuid.UUID,
        *,
        plan_tier: str | None = None,
        subscription_status: str | None = None,
        trial_ends_at: datetime | None = None,
    ) -> Tenant:
        """Update billing fields on a tenant (partial update, flush + refresh)."""
        values: dict[str, Any] = {}
        if plan_tier is not None:
            values["plan_tier"] = plan_tier
        if subscription_status is not None:
            values["subscription_status"] = subscription_status
        if trial_ends_at is not None:
            values["trial_ends_at"] = trial_ends_at
        if not values:
            return await self._require_by_id(tenant_id)
        stmt = update(TenantModel).where(TenantModel.id == tenant_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()
        return await self._require_by_id(tenant_id)

    async def mark_trial_expired_if_past(self, tenant_id: str | uuid.UUID, now: datetime) -> bool:
        """Atomically flip trialing→expired when trial has passed (idempotent).

        Returns True if a row was updated, False if already expired/active/none.
        Uses a conditional UPDATE to avoid read-modify-write races.
        """
        stmt = (
            update(TenantModel)
            .where(
                TenantModel.id == tenant_id,
                TenantModel.subscription_status == "trialing",
                TenantModel.trial_ends_at.isnot(None),
                TenantModel.trial_ends_at < now,
            )
            .values(subscription_status="expired")
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        await self.session.flush()
        return result.rowcount > 0

    async def mark_onboarding_complete(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Stamp onboarding_completed_at (idempotent) and flush."""
        model = await self.session.get(TenantModel, tenant_id)
        if model is None:
            raise TenantNotFoundError("Organization not found")
        if model.onboarding_completed_at is None:
            model.onboarding_completed_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def _require_by_id(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Fetch by ID, raising TenantNotFoundError when absent."""
        tenant = await self.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError("Organization not found")
        return tenant
