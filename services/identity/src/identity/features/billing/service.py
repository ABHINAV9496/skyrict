"""Billing service - subscription reads, plan changes, and gate enforcement.

The service is the sole business-rules layer for billing operations. All
persistence goes through ``TenantRepository``; the service never touches
ORM models directly.

**Trial lifecycle** — a 14-day trial starts at org provisioning. The
server-side lazy-flip (``refresh_subscription``) atomically marks
``subscription_status='expired'`` once ``trial_ends_at`` has passed. No
background job is required for this gate: the flip happens on every read
and is race-free via a conditional UPDATE.

**402 vs 403 convention** — ``require_plan_access`` distinguishes two
failure modes:
  * **403 PermissionDeniedError** — the tenant has an active account but
    the requested feature is not on their plan tier (wrong plan, not a
    billing issue).
  * **402 PaymentRequiredError** — the tenant's subscription is
    inactive (``none`` or ``expired``), so a paid plan must be activated
    before the feature can be accessed.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from identity.domain.entities import Tenant
from identity.features.billing.plans import PLANS, resolve_plan_id, resolve_tier
from skyrict_common.exceptions import (
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    ValidationError,
)

if TYPE_CHECKING:
    from identity.features.organizations.repository import TenantRepository

_FREE_TIER = "free"


class BillingService:
    """Encapsulates all billing business rules."""

    def __init__(
        self,
        tenant_repo: TenantRepository,
        *,
        now: datetime | None = None,
    ) -> None:
        self._tenant_repo = tenant_repo
        self._now = now

    # -- Internal helpers -----------------------------------------------------

    @property
    def _utcnow(self) -> datetime:
        """Return the current UTC time. Overridable for deterministic tests."""
        return self._now if self._now is not None else datetime.now(UTC)

    async def _require_tenant(self, tenant_id: str | uuid.UUID) -> Tenant:
        tenant = await self._tenant_repo.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError("Organization not found")
        return tenant

    # -- Subscription read ----------------------------------------------------

    async def refresh_subscription(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Atomically flip trialing→expired when trial has passed (idempotent).

        Returns the (possibly updated) tenant. The conditional UPDATE avoids
        read-modify-write races under concurrent subscription reads.
        """
        await self._tenant_repo.mark_trial_expired_if_past(tenant_id, self._utcnow)
        return await self._require_tenant(tenant_id)

    async def get_subscription(self, tenant_id: str | uuid.UUID) -> dict[str, Any]:
        """Return subscription state suitable for ``SubscriptionResponse``."""
        tenant = await self.refresh_subscription(tenant_id)
        plan_id = resolve_plan_id(tenant.plan_tier)
        return {
            "plan_id": plan_id,
            "plan_tier": tenant.plan_tier,
            "subscription_status": tenant.subscription_status,
            "trial_ends_at": tenant.trial_ends_at,
            "days_remaining": self._compute_days_remaining(tenant),
            "billing_email": tenant.billing_email,
        }

    # -- Plan read / update ---------------------------------------------------

    async def get_plan(self, tenant_id: str | uuid.UUID) -> dict[str, Any]:
        """Return the tenant's current plan as a catalog entry dict."""
        tenant = await self._require_tenant(tenant_id)
        return self._catalog_entry(tenant.plan_tier)

    async def list_plans(self) -> list[dict[str, Any]]:
        """Return the full paid-plan catalog in canonical (insertion) order."""
        return [plan.model_dump() for plan in PLANS.values()]

    async def update_plan(self, tenant_id: str | uuid.UUID, plan_id: str) -> dict[str, Any]:
        """Switch the tenant's plan.  No-op when the tier is unchanged.

        Emits ``billing.plan.changed`` only when the tier actually changes.
        ``subscription_status`` and ``trial_ends_at`` are left untouched
        (payment integration is the scope of BILLING-SERV-002).
        """
        if plan_id not in PLANS:
            raise ValidationError(f"Unknown plan: {plan_id}")
        tenant = await self._require_tenant(tenant_id)
        new_tier = resolve_tier(plan_id)
        if tenant.plan_tier == new_tier:
            return self._catalog_entry(tenant.plan_tier)

        previous_tier = tenant.plan_tier
        updated = await self._tenant_repo.update_billing(tenant_id, plan_tier=new_tier)

        await self._emit_plan_changed(
            tenant_id=tenant_id,
            previous_tier=previous_tier,
            new_tier=new_tier,
            subscription_status=updated.subscription_status,
            trial_ends_at=updated.trial_ends_at,
        )

        return self._catalog_entry(new_tier)

    # -- Gate enforcement -----------------------------------------------------

    async def effective_tier(self, tenant_id: str | uuid.UUID) -> str:
        """Resolve the tenant's effective plan tier for gate checks.

        Returns the stored ``plan_tier`` only when the subscription is
        ``active`` or the trial is still in progress.  Otherwise returns
        ``'free'``.
        """
        tenant = await self.refresh_subscription(tenant_id)
        return self._effective_tier(tenant)

    async def require_plan_access(
        self, tenant_id: str | uuid.UUID, required_tiers: tuple[str, ...]
    ) -> None:
        """Enforce the plan gate: raise 403/402 when access is not granted.

        Raises:
            PermissionDeniedError: The tenant has an active subscription but
                its effective tier is not in ``required_tiers``.
            PaymentRequiredError: The subscription is inactive (none/expired),
                so the feature cannot be unlocked without a paid plan.
        """
        tenant = await self.refresh_subscription(tenant_id)
        if self._effective_tier(tenant) in required_tiers:
            return
        if tenant.subscription_status in ("active", "trialing"):
            raise PermissionDeniedError("This feature requires a higher plan tier")
        raise PaymentRequiredError("An active subscription is required to access this feature")

    # -- Private helpers ------------------------------------------------------

    def _effective_tier(self, tenant: Tenant) -> str:
        """Compute effective tier from a loaded tenant entity."""
        if tenant.subscription_status == "trialing":
            if tenant.trial_ends_at is not None and tenant.trial_ends_at > self._utcnow:
                return tenant.plan_tier
            return _FREE_TIER
        if tenant.subscription_status == "active":
            return tenant.plan_tier
        # none / expired / past_due / canceled  →  treat as free
        return _FREE_TIER

    def _compute_days_remaining(self, tenant: Tenant) -> int:
        """Whole days remaining in the trial (ceiling, 0 when expired/none).

        ``math.ceil`` ensures a user with 23 hours left sees 1 day, not 0.
        """
        if tenant.subscription_status != "trialing" or tenant.trial_ends_at is None:
            return 0
        delta = tenant.trial_ends_at - self._utcnow
        if delta.total_seconds() <= 0:
            return 0
        return max(0, math.ceil(delta.total_seconds() / 86400))

    @staticmethod
    def _catalog_entry(tier: str) -> dict[str, Any]:
        """Resolve a DB tier to the full catalog Plan dict."""
        plan_id = resolve_plan_id(tier)
        plan = PLANS.get(plan_id)
        if plan is not None:
            return plan.model_dump()
        # Fallback for unknown legacy tiers → free
        return {
            "id": _FREE_TIER,
            "tier": _FREE_TIER,
            "display_name": "Free",
            "monthly_price_cents": 0,
            "annual_price_cents": 0,
            "features": {
                "max_users": None,
                "ai_credits_monthly": None,
                "max_agents": None,
                "modules": [],
            },
        }

    async def _emit_plan_changed(
        self,
        *,
        tenant_id: str | uuid.UUID,
        previous_tier: str,
        new_tier: str,
        subscription_status: str,
        trial_ends_at: datetime | None,
    ) -> None:
        """Emit the plan-changed domain event (non-blocking stub)."""
        from identity.events.producers.billing_events import emit_plan_changed

        await emit_plan_changed(
            tenant_id=tenant_id,
            previous_tier=previous_tier,
            new_tier=new_tier,
            subscription_status=subscription_status,
            trial_ends_at=trial_ends_at,
        )
