"""Tenant repository - DB operations for the tenants table.

All SQLAlchemy stays in this file. Service-facing methods accept and return
domain entities (``identity.domain.entities.Tenant``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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
        "grace_started_at": tenant.grace_started_at,
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
        grace_started_at=model.grace_started_at,
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

    async def get_by_stripe_customer_id(self, stripe_customer_id: str) -> Tenant | None:
        """Fetch a tenant by Stripe customer id (origin for webhooks)."""
        stmt = select(TenantModel).where(TenantModel.stripe_customer_id == stripe_customer_id)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def get_by_stripe_subscription_id(self, stripe_subscription_id: str) -> Tenant | None:
        """Fetch a tenant by Stripe subscription id (origin for webhooks)."""
        stmt = select(TenantModel).where(
            TenantModel.stripe_subscription_id == stripe_subscription_id
        )
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
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        billing_email: str | None = None,
        grace_started_at: datetime | None = None,
    ) -> Tenant:
        """Update billing fields on a tenant (partial update, flush + refresh)."""
        values: dict[str, Any] = {}
        if plan_tier is not None:
            values["plan_tier"] = plan_tier
        if subscription_status is not None:
            values["subscription_status"] = subscription_status
        if trial_ends_at is not None:
            values["trial_ends_at"] = trial_ends_at
        if stripe_customer_id is not None:
            values["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            values["stripe_subscription_id"] = stripe_subscription_id
        if billing_email is not None:
            values["billing_email"] = billing_email
        if grace_started_at is not None:
            values["grace_started_at"] = grace_started_at
        if not values:
            return await self._require_by_id(tenant_id)
        stmt = update(TenantModel).where(TenantModel.id == tenant_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()
        return await self._require_by_id(tenant_id)

    async def apply_subscription_status(
        self,
        tenant_id: str | uuid.UUID,
        status: str,
        *,
        now: datetime,
        grace_days: int = 7,
    ) -> Tenant:
        """Mirror a Stripe subscription status atomically (race-free).

        Grace-clock rules (BILLING-SERV-002):
        * ``past_due`` starts the grace clock ONCE: the conditional UPDATE
          guards on the current status not already being ``past_due``, so a
          duplicate delivery of the same past_due event cannot reset
          ``grace_started_at``.
        * ``active`` clears the clock in the same statement that flips the
          status, so a stale ``grace_started_at`` can never survive into a
          later ``past_due`` (past_due -> active -> past_due gets a fresh
          clock each period).
        """
        if status == "past_due":
            stmt = (
                update(TenantModel)
                .where(
                    TenantModel.id == tenant_id,
                    TenantModel.subscription_status != "past_due",
                )
                .values(subscription_status="past_due", grace_started_at=now)
            )
        elif status == "active":
            stmt = (
                update(TenantModel)
                .where(TenantModel.id == tenant_id)
                .values(subscription_status="active", grace_started_at=None)
            )
        else:
            stmt = (
                update(TenantModel)
                .where(TenantModel.id == tenant_id)
                .values(subscription_status=status)
            )
        await self.session.execute(stmt)
        await self.session.flush()
        return await self._require_by_id(tenant_id)

    async def mark_grace_expired_if_past(
        self,
        tenant_id: str | uuid.UUID,
        now: datetime,
        grace_days: int,
    ) -> bool:
        """Atomically soft-downgrade a past_due tenant whose grace lapsed.

        Conditional UPDATE guards on ``subscription_status='past_due'`` with a
        set ``grace_started_at`` older than ``now - grace_days``. Returns True
        when the downgrade ran, False otherwise (idempotent). Nulls the clock
        in the same statement so the transition cannot re-fire.
        """
        cutoff = now - timedelta(days=grace_days)
        stmt = (
            update(TenantModel)
            .where(
                TenantModel.id == tenant_id,
                TenantModel.subscription_status == "past_due",
                TenantModel.grace_started_at.isnot(None),
                TenantModel.grace_started_at < cutoff,
            )
            .values(
                subscription_status="free",
                plan_tier="free",
                grace_started_at=None,
            )
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        await self.session.flush()
        return result.rowcount > 0

    async def downgrade_to_free(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Soft-downgrade a tenant to the free tier (idempotent, never locks out).

        Used by ``customer.subscription.deleted`` and any immediate-downgrade
        path: plan becomes free, subscription is closed, data is preserved.
        """
        stmt = (
            update(TenantModel)
            .where(TenantModel.id == tenant_id)
            .values(
                plan_tier="free",
                subscription_status="free",
                grace_started_at=None,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
        return await self._require_by_id(tenant_id)

    async def mark_event_processed(
        self,
        event_id: str,
        event_type: str,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> bool:
        """Mark a Stripe event processed (persisted idempotency guard).

        ``INSERT ... ON CONFLICT (event_id) DO NOTHING`` - returns True when
        this call created the marker (first delivery) and False when the event
        was already processed (duplicate delivery). Runs inside the caller's
        transaction, so a rolled-back state mutation also rolls back the
        marker (at-least-once, no partial state). The unique constraint makes
        concurrent duplicate deliveries safe: only one insert can win.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from identity.models.stripe_event import ProcessedStripeEventModel

        stmt = pg_insert(ProcessedStripeEventModel).values(
            event_id=event_id,
            event_type=event_type,
            tenant_id=tenant_id,
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        await self.session.flush()
        return result.rowcount > 0

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
