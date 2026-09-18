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

from identity.core.config import settings
from identity.domain.entities import Tenant
from identity.features.billing.plans import PLANS, resolve_plan_id, resolve_tier
from skyrict_common.exceptions import (
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    ServiceUnavailableError,
    ValidationError,
)

if TYPE_CHECKING:
    from identity.core.stripe import StripeClient
    from identity.features.audit.service import AuditService
    from identity.features.organizations.repository import TenantRepository

_FREE_TIER = "free"


class BillingService:
    """Encapsulates all billing business rules."""

    def __init__(
        self,
        tenant_repo: TenantRepository,
        *,
        now: datetime | None = None,
        audit_service: AuditService | None = None,
        stripe_client: StripeClient | None = None,
    ) -> None:
        self._tenant_repo = tenant_repo
        self._now = now
        # Fallback is for test ergonomics only: unit tests construct
        # ``BillingService(repo)`` without an audit service. Production wiring
        # (identity.api.deps.get_billing_service) ALWAYS injects one, so a
        # missing audit record cannot happen through the DI graph. Do not
        # make this parameter required.
        self._audit_service = audit_service
        # Same ergonomics for the Stripe boundary: without an injected client
        # (or with a disabled one) session creation fails with a sanitized 503
        # instead of crashing on a missing dependency.
        self._stripe_client = stripe_client

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

    @property
    def _grace_days(self) -> int:
        """Grace period length after 'past_due', read live so tests can override."""
        return settings.BILLING_GRACE_PERIOD_DAYS

    async def refresh_subscription(self, tenant_id: str | uuid.UUID) -> Tenant:
        """Apply lazy expiry checks and return the authoritative tenant state.

        Runs two conditional-UPDATE checks (idempotent, race-free):
          1. trial expiry  - trialing -> expired when ``trial_ends_at`` passes.
          2. grace expiry  - past_due -> free when ``grace_started_at`` exceeds
             ``BILLING_GRACE_PERIOD_DAYS`` (soft downgrade; data preserved).
        Both flip on every read, so no scheduler is required - the same
        lazy-on-read pattern the trial already uses.
        """
        await self._tenant_repo.mark_trial_expired_if_past(tenant_id, self._utcnow)
        tenant = await self._require_tenant(tenant_id)
        if tenant.subscription_status == "past_due":
            previous_tier = tenant.plan_tier
            if await self._tenant_repo.mark_grace_expired_if_past(
                tenant_id, self._utcnow, self._grace_days
            ):
                await self._emit_audit(
                    action="billing.downgraded",
                    target=f"tenant:{tenant_id}",
                    details={
                        "reason": "grace_expired",
                        "previous_tier": previous_tier,
                        "previous_status": "past_due",
                        "grace_days": self._grace_days,
                    },
                    tenant_id=str(tenant_id),
                )
                tenant = await self._require_tenant(tenant_id)
        return tenant

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

    # -- Stripe sessions (BILLING-UI-004) -------------------------------------

    async def create_checkout_session(
        self, tenant_id: str | uuid.UUID, plan_id: str, interval: str
    ) -> dict[str, Any]:
        """Create a Stripe Checkout session for a paid plan.

        The owner's browser is redirected to the returned ``url``; Stripe
        redirects back to the app's billing settings page on completion. The
        session carries the tenant id as ``client_reference_id`` so the
        ``checkout.session.completed`` webhook can resolve the tenant.

        Raises:
            ValidationError: unknown plan or interval, or no Stripe Price is
                configured for the plan+interval (Starter is free and
                Enterprise is custom-priced - neither is purchasable via
                Checkout).
            ServiceUnavailableError: Stripe is not configured or the app URL
                for redirects is missing (503, sanitized).
        """
        if plan_id not in PLANS:
            raise ValidationError(f"Unknown plan: {plan_id}")
        if interval not in ("month", "year"):
            raise ValidationError(f"Unknown billing interval: {interval}")
        price_id = settings.BILLING_STRIPE_PRICE_IDS.get(f"{plan_id}:{interval}")
        if not price_id:
            raise ValidationError(f"No Stripe price is configured for {plan_id} ({interval})")
        if self._stripe_client is None or not self._stripe_client.enabled:
            raise ServiceUnavailableError("Stripe is not configured")

        tenant = await self._require_tenant(tenant_id)
        if not tenant.stripe_customer_id:
            tenant = await self._create_stripe_customer(tenant)
        assert tenant.stripe_customer_id is not None  # set by _create_stripe_customer
        app_url = self._billing_app_url(tenant)
        session = self._stripe_client.create_checkout_session(
            customer_id=tenant.stripe_customer_id,
            price_id=price_id,
            success_url=f"{app_url}/dashboard/settings/billing?checkout=success",
            cancel_url=f"{app_url}/dashboard/settings/billing?checkout=cancelled",
            client_reference_id=str(tenant.id),
            metadata={"tenant_id": str(tenant.id), "plan_id": plan_id, "interval": interval},
        )
        await self._emit_audit(
            action="billing.checkout.created",
            target=f"tenant:{tenant_id}",
            details={
                "plan_id": plan_id,
                "interval": interval,
                "stripe_session_id": session["id"],
            },
            tenant_id=str(tenant_id),
        )
        return {"session_id": session["id"], "url": session["url"]}

    async def create_portal_session(self, tenant_id: str | uuid.UUID) -> dict[str, Any]:
        """Create a Stripe Customer Portal session to manage billing.

        The owner's browser is redirected to the returned ``url``; Stripe
        returns them to the billing settings page when they close the portal.

        Raises:
            PaymentRequiredError: the tenant has no Stripe customer yet (no
                prior checkout), so there is nothing to manage in the portal.
            ServiceUnavailableError: Stripe is not configured or the app URL
                for redirects is missing (503, sanitized).
        """
        if self._stripe_client is None or not self._stripe_client.enabled:
            raise ServiceUnavailableError("Stripe is not configured")
        tenant = await self._require_tenant(tenant_id)
        customer_id = tenant.stripe_customer_id
        if not customer_id:
            raise PaymentRequiredError(
                "An active subscription is required to manage billing settings"
            )
        session = self._stripe_client.create_portal_session(
            customer_id=customer_id,
            return_url=f"{self._billing_app_url(tenant)}/dashboard/settings/billing",
        )
        await self._emit_audit(
            action="billing.portal.opened",
            target=f"tenant:{tenant_id}",
            details={
                "stripe_customer_id": tenant.stripe_customer_id,
                "stripe_session_id": session["id"],
            },
            tenant_id=str(tenant_id),
        )
        return {"session_id": session["id"], "url": session["url"]}

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

    # -- Stripe webhook lifecycle (BILLING-SERV-002) --------------------------

    async def handle_stripe_event(
        self,
        *,
        event_id: str,
        event_type: str,
        event_object: dict[str, Any],
    ) -> str:
        """Apply a signature-verified Stripe event, idempotently.

        Returns ``applied`` (state changed), ``skipped`` (duplicate delivery of
        a processed event), or ``ignored`` (event type we do not handle, still
        acknowledged so Stripe stops retrying). The idempotency marker is
        written in the same transaction as the state mutation, so a failed
        handler rolls back its marker and Stripe's retry re-runs it cleanly.
        """
        event_type = event_type or ""
        tenant = await self._resolve_event_tenant(event_type, event_object)

        first_delivery = await self._tenant_repo.mark_event_processed(
            event_id,
            event_type,
            tenant_id=tenant.id if tenant is not None else None,
        )
        if not first_delivery:
            return "skipped"

        if event_type == "checkout.session.completed":
            await self._handle_checkout_completed(event_object, tenant)
            return "applied"
        if event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(event_object, tenant)
            return "applied"
        if event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(event_object, tenant)
            return "applied"
        return "ignored"

    async def _resolve_event_tenant(
        self, event_type: str, event_object: dict[str, Any]
    ) -> Tenant | None:
        """Locate the tenant an event targets (None when orphaned)."""
        if event_type == "checkout.session.completed":
            reference = event_object.get("client_reference_id")
            if reference:
                tenant = await self._tenant_repo.get_by_id(reference)
                if tenant is not None:
                    return tenant
        if event_object.get("customer"):
            tenant = await self._tenant_repo.get_by_stripe_customer_id(event_object["customer"])
            if tenant is not None:
                return tenant
        if event_object.get("id") and event_type.startswith("customer.subscription"):
            return await self._tenant_repo.get_by_stripe_subscription_id(event_object["id"])
        return None

    async def _handle_checkout_completed(
        self, session: dict[str, Any], tenant: Tenant | None
    ) -> None:
        """Persist Stripe ids after checkout and activate the subscription.

        The checkout session does not carry trial state; Stripe always follows
        checkout with ``customer.subscription.created/updated`` events, which
        mirror ``trialing`` on the next delivery. Marking ``active`` now and
        letting that event correct the status is the standard integration flow.
        """
        if tenant is None or tenant.id is None:
            return
        tenant_id = tenant.id
        customer_id = session.get("customer")
        subscription_id = session.get("subscription")
        customer_details = session.get("customer_details") or {}
        await self._tenant_repo.update_billing(
            tenant_id,
            subscription_status="active",
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            billing_email=customer_details.get("email"),
        )
        await self._emit_audit(
            action="billing.checkout.completed",
            target=f"tenant:{tenant_id}",
            details={
                "stripe_customer_id": customer_id,
                "stripe_subscription_id": subscription_id,
                "plan_tier": tenant.plan_tier,
            },
            tenant_id=str(tenant_id),
        )

    async def _handle_subscription_updated(
        self, subscription: dict[str, Any], tenant: Tenant | None
    ) -> None:
        """Mirror Stripe's subscription status atomically.

        ``past_due`` starts the grace clock ONCE (guarded by the repository);
        ``active`` clears it in the same statement, so a later past_due starts
        a fresh window (past_due -> active -> past_due never reuses a stale
        clock).
        """
        if tenant is None or tenant.id is None:
            return
        tenant_id = tenant.id
        previous = await self._require_tenant(tenant_id)
        new_status = subscription.get("status") or previous.subscription_status
        updated = await self._tenant_repo.apply_subscription_status(
            tenant_id, new_status, now=self._utcnow
        )
        await self._emit_audit(
            action="billing.subscription.updated",
            target=f"tenant:{tenant_id}",
            details={
                "previous_status": previous.subscription_status,
                "new_status": updated.subscription_status,
            },
            tenant_id=str(tenant_id),
        )
        if new_status == "past_due" and previous.subscription_status != "past_due":
            await self._emit_audit(
                action="billing.grace.started",
                target=f"tenant:{tenant_id}",
                details={"grace_days": self._grace_days},
                tenant_id=str(tenant_id),
            )

    async def _handle_subscription_deleted(
        self, subscription: dict[str, Any], tenant: Tenant | None
    ) -> None:
        """Soft-downgrade on cancellation - never locks owners/members out.

        All data and access are preserved: only plan_tier and the subscription
        state drop to ``free``.
        """
        if tenant is None or tenant.id is None:
            return
        tenant_id = tenant.id
        previous = await self._require_tenant(tenant_id)
        await self._tenant_repo.downgrade_to_free(tenant_id)
        await self._emit_audit(
            action="billing.subscription.deleted",
            target=f"tenant:{tenant_id}",
            details={"stripe_subscription_id": subscription.get("id")},
            tenant_id=str(tenant_id),
        )
        await self._emit_audit(
            action="billing.downgraded",
            target=f"tenant:{tenant_id}",
            details={
                "reason": "subscription_deleted",
                "previous_tier": previous.plan_tier,
                "previous_status": previous.subscription_status,
            },
            tenant_id=str(tenant_id),
        )

    async def tick(self, tenant_id: str | uuid.UUID) -> dict[str, Any]:
        """Explicit lazy-check trigger for ops/cron (same path as reads).

        Runs the trial + grace expiry checks and reports whether subscription
        state changed, so callers can observe the transition.
        """
        before = await self._require_tenant(tenant_id)
        after = await self.refresh_subscription(tenant_id)
        changed = (
            before.subscription_status != after.subscription_status
            or before.plan_tier != after.plan_tier
        )
        return {"tenant_id": str(tenant_id), "checked": True, "changed": changed}

    # -- Private helpers ------------------------------------------------------

    async def _create_stripe_customer(self, tenant: Tenant) -> Tenant:
        """Lazily create the tenant's Stripe customer and persist its id.

        Called on first checkout so the session has a customer to attach to.
        The persisted id is then reused by every later session and matched by
        the ``customer.subscription.*`` webhook handlers.
        """
        assert self._stripe_client is not None  # guarded by callers
        assert tenant.id is not None  # loaded from the repo
        customer = self._stripe_client.create_customer(
            email=tenant.billing_email,
            metadata={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
        )
        return await self._tenant_repo.update_billing(tenant.id, stripe_customer_id=customer["id"])

    def _billing_app_url(self, tenant: Tenant) -> str:
        """Resolve the app origin for Stripe redirects (BILLING_APP_URL).

        A single ``{slug}`` placeholder is replaced with the tenant slug for
        workspace subdomains; otherwise the URL is used verbatim.
        """
        base = settings.BILLING_APP_URL.strip().rstrip("/")
        if not base:
            raise ServiceUnavailableError(
                "Billing is not configured - set BILLING_APP_URL to enable Stripe redirects"
            )
        return base.replace("{slug}", tenant.slug)

    def _effective_tier(self, tenant: Tenant) -> str:
        """Compute effective tier from a loaded tenant entity."""
        if tenant.subscription_status == "trialing":
            if tenant.trial_ends_at is not None and tenant.trial_ends_at > self._utcnow:
                return tenant.plan_tier
            return _FREE_TIER
        if tenant.subscription_status in ("active", "past_due"):
            # past_due keeps the paid tier for the grace window: the lazy
            # refresh_subscription downgrades to free once grace lapses, so a
            # tenant can never be served a tier past its grace period (never
            # locks owners/members out mid-payment-interruption).
            return tenant.plan_tier
        # none / expired / free / canceled  →  treat as free
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

    async def _emit_audit(
        self,
        *,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Write a billing lifecycle audit entry (no-op when no service wired)."""
        if self._audit_service is None:
            return
        await self._audit_service.log(
            action=action,
            target=target,
            details=details,
            tenant_id=tenant_id,
        )

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
