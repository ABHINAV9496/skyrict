"""Unit tests for the billing service (SKY-35) with a fake persistent repo.

Covers subscription reads, the lazy trial-expiry flip, plan updates, the plan
gate matrix (403 vs 402), no-op/idempotent behaviour, webhook lifecycle, and
Stripe checkout/portal session creation (BILLING-UI-004).
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from identity.core.config import settings
from identity.domain.entities import Tenant
from identity.features.billing.plans import resolve_plan_id
from identity.features.billing.service import BillingService
from skyrict_common.exceptions import (
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    ServiceUnavailableError,
    ValidationError,
)


class FakeTenantRepo:
    """In-memory TenantRepository double implementing the billing methods."""

    def __init__(self, tenants: list[Tenant] | None = None) -> None:
        self.tenants: dict[uuid.UUID, Tenant] = {}
        for tenant in tenants or []:
            tenant.id = tenant.id or uuid.uuid4()
            self.tenants[tenant.id] = tenant
        self.expired_flips: list[uuid.UUID] = []
        self.grace_flips: list[uuid.UUID] = []
        self.processed_events: set[str] = set()

    async def get_by_id(self, tenant_id: str | uuid.UUID) -> Tenant | None:
        tenant = self.tenants.get(uuid.UUID(str(tenant_id)))
        return copy.copy(tenant) if tenant is not None else None

    async def get_by_stripe_customer_id(self, customer_id: str) -> Tenant | None:
        for tenant in self.tenants.values():
            if tenant.stripe_customer_id == customer_id:
                return copy.copy(tenant)
        return None

    async def get_by_stripe_subscription_id(self, subscription_id: str) -> Tenant | None:
        for tenant in self.tenants.values():
            if tenant.stripe_subscription_id == subscription_id:
                return copy.copy(tenant)
        return None

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
    ) -> Tenant:
        tenant = self.tenants[uuid.UUID(str(tenant_id))]
        if plan_tier is not None:
            tenant.plan_tier = plan_tier
        if subscription_status is not None:
            tenant.subscription_status = subscription_status
        if trial_ends_at is not None:
            tenant.trial_ends_at = trial_ends_at
        if stripe_customer_id is not None:
            tenant.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id is not None:
            tenant.stripe_subscription_id = stripe_subscription_id
        if billing_email is not None:
            tenant.billing_email = billing_email
        return tenant

    async def mark_trial_expired_if_past(self, tenant_id: str | uuid.UUID, now: datetime) -> bool:
        tenant = self.tenants.get(uuid.UUID(str(tenant_id)))
        if (
            tenant is not None
            and tenant.subscription_status == "trialing"
            and tenant.trial_ends_at is not None
            and tenant.trial_ends_at < now
        ):
            tenant.subscription_status = "expired"
            self.expired_flips.append(uuid.UUID(str(tenant_id)))
            return True
        return False

    async def apply_subscription_status(
        self,
        tenant_id: str | uuid.UUID,
        subscription_status: str,
        *,
        now: datetime,
    ) -> Tenant:
        tenant = self.tenants[uuid.UUID(str(tenant_id))]
        if subscription_status == "past_due":
            if tenant.subscription_status != "past_due":
                tenant.grace_started_at = now
            tenant.subscription_status = "past_due"
        elif subscription_status == "active":
            tenant.subscription_status = "active"
            tenant.grace_started_at = None
        else:
            tenant.subscription_status = subscription_status
        return tenant

    async def mark_grace_expired_if_past(
        self,
        tenant_id: str | uuid.UUID,
        now: datetime,
        grace_days: int,
    ) -> bool:
        tenant = self.tenants.get(uuid.UUID(str(tenant_id)))
        if (
            tenant is not None
            and tenant.subscription_status == "past_due"
            and tenant.grace_started_at is not None
            and tenant.grace_started_at < now - timedelta(days=grace_days)
        ):
            tenant.subscription_status = "free"
            tenant.plan_tier = "free"
            tenant.grace_started_at = None
            self.grace_flips.append(uuid.UUID(str(tenant_id)))
            return True
        return False

    async def downgrade_to_free(self, tenant_id: str | uuid.UUID) -> Tenant:
        tenant = self.tenants[uuid.UUID(str(tenant_id))]
        tenant.plan_tier = "free"
        tenant.subscription_status = "free"
        tenant.grace_started_at = None
        return tenant

    async def mark_event_processed(
        self,
        event_id: str,
        event_type: str,
        *,
        tenant_id: str | uuid.UUID | None = None,
    ) -> bool:
        if event_id in self.processed_events:
            return False
        self.processed_events.add(event_id)
        return True


class FakeAuditService:
    """Records log() calls exactly as the production AuditService would."""

    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def log(
        self,
        *,
        action: str,
        target: str,
        user_id: str | None = None,
        details: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.entries.append(
            {
                "action": action,
                "target": target,
                "user_id": user_id,
                "details": details,
                "tenant_id": tenant_id,
            }
        )


class FakeStripeClient:
    """Minimal StripeClient double mirroring the real sync SDK surface."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.created_customers: list[dict[str, Any]] = []
        self.created_checkout_sessions: list[dict[str, Any]] = []
        self.created_portal_sessions: list[dict[str, Any]] = []

    def create_customer(
        self, *, email: str | None = None, metadata: dict[str, str] | None = None
    ) -> dict[str, str]:
        customer_id = f"cus_{len(self.created_customers) + 1}"
        self.created_customers.append(
            {"id": customer_id, "email": email, "metadata": metadata or {}}
        )
        return {"id": customer_id}

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        client_reference_id: str,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, str]:
        session_id = f"cs_{len(self.created_checkout_sessions) + 1}"
        self.created_checkout_sessions.append(
            {
                "id": session_id,
                "customer_id": customer_id,
                "price_id": price_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": client_reference_id,
                "metadata": metadata or {},
            }
        )
        return {"id": session_id, "url": f"https://checkout.stripe.com/c/pay/{session_id}"}

    def create_portal_session(self, *, customer_id: str, return_url: str) -> dict[str, str]:
        session_id = f"ps_{len(self.created_portal_sessions) + 1}"
        self.created_portal_sessions.append(
            {"id": session_id, "customer_id": customer_id, "return_url": return_url}
        )
        return {"id": session_id, "url": f"https://billing.stripe.com/p/session/{session_id}"}


@pytest.fixture(autouse=True)
def _stripe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point session creation at a fake app origin and a minimal price map."""
    monkeypatch.setattr(settings, "BILLING_APP_URL", "https://{slug}.acme.test")
    monkeypatch.setattr(
        settings,
        "BILLING_STRIPE_PRICE_IDS",
        {
            "professional:month": "price_pro_month",
            "professional:year": "price_pro_year",
            "business:month": "price_biz_month",
            "business:year": "price_biz_year",
        },
    )


def _tenant(
    *,
    plan_tier: str = "pro",
    subscription_status: str = "trialing",
    trial_ends_at: datetime | None = None,
    grace_started_at: datetime | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    billing_email: str | None = None,
) -> Tenant:
    return Tenant(
        name="Acme",
        slug="acme",
        plan_tier=plan_tier,
        subscription_status=subscription_status,
        trial_ends_at=trial_ends_at,
        grace_started_at=grace_started_at,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
        billing_email=billing_email,
    )


def _service(
    repo: FakeTenantRepo,
    now: datetime | None = None,
    audit: FakeAuditService | None = None,
    stripe: FakeStripeClient | None = None,
) -> BillingService:
    return BillingService(repo, now=now, audit_service=audit, stripe_client=stripe)


def _trial_ends(days_from_now: float = 10.0) -> datetime:
    return datetime.now(UTC) + timedelta(days=days_from_now)


class TestGetSubscription:
    async def test_trialing_subscription_maps_tier_and_days(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(10))])
        svc = _service(repo)

        sub = await svc.get_subscription(str(next(iter(repo.tenants))))

        assert sub["plan_tier"] == "pro"
        assert sub["plan_id"] == resolve_plan_id("pro")
        assert sub["subscription_status"] == "trialing"
        assert sub["days_remaining"] == 10
        assert sub["billing_email"] is None

    async def test_days_remaining_ceil_rounds_partial_day_up(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(0.5))])
        svc = _service(repo)

        sub = await svc.get_subscription(str(next(iter(repo.tenants))))

        assert sub["days_remaining"] == 1

    async def test_past_trial_flips_to_expired_lazily(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(-1))])
        svc = _service(repo)
        tenant_id = str(next(iter(repo.tenants)))

        sub = await svc.get_subscription(tenant_id)

        assert sub["subscription_status"] == "expired"
        assert sub["days_remaining"] == 0
        assert [uuid.UUID(tenant_id)] == repo.expired_flips

    async def test_legacy_tenant_none_status_reads_zero(self) -> None:
        repo = FakeTenantRepo([_tenant(subscription_status="none", trial_ends_at=None)])
        svc = _service(repo)

        sub = await svc.get_subscription(str(next(iter(repo.tenants))))

        assert sub["subscription_status"] == "none"
        assert sub["days_remaining"] == 0
        assert sub["plan_tier"] == "pro"

    async def test_missing_tenant_raises_not_found(self) -> None:
        svc = _service(FakeTenantRepo())

        with pytest.raises(NotFoundError):
            await svc.get_subscription(uuid.uuid4())


class TestRefreshSubscription:
    async def test_refresh_is_idempotent_after_flip(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(-1))])
        svc = _service(repo)
        tenant_id = str(next(iter(repo.tenants)))

        await svc.refresh_subscription(tenant_id)
        await svc.refresh_subscription(tenant_id)

        assert len(repo.expired_flips) == 1
        assert repo.tenants[uuid.UUID(tenant_id)].subscription_status == "expired"


class TestGetPlan:
    async def test_returns_catalog_entry_for_current_tier(self) -> None:
        repo = FakeTenantRepo([_tenant(plan_tier="pro")])
        svc = _service(repo)

        plan = await svc.get_plan(str(next(iter(repo.tenants))))

        assert plan["id"] == "professional"
        assert plan["tier"] == "pro"
        assert plan["monthly_price_cents"] == 2_900

    async def test_unknown_tier_falls_back_to_free(self) -> None:
        repo = FakeTenantRepo([_tenant(plan_tier="mystery")])
        svc = _service(repo)

        plan = await svc.get_plan(str(next(iter(repo.tenants))))

        assert plan["id"] == "free"
        assert plan["monthly_price_cents"] == 0


class TestListPlans:
    async def test_returns_all_four_catalog_plans_in_order(self) -> None:
        svc = _service(FakeTenantRepo())

        plans = await svc.list_plans()

        assert [p["id"] for p in plans] == [
            "starter",
            "professional",
            "business",
            "enterprise",
        ]


class TestUpdatePlan:
    async def test_rejects_unknown_plan_id(self) -> None:
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo)

        with pytest.raises(ValidationError):
            await svc.update_plan(str(next(iter(repo.tenants))), "luxury")

    async def test_same_tier_is_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple] = []

        async def _fake_emit(**kwargs) -> None:
            calls.append(kwargs)

        monkeypatch.setattr(
            "identity.events.producers.billing_events.emit_plan_changed", _fake_emit
        )
        repo = FakeTenantRepo([_tenant(plan_tier="pro")])
        svc = _service(repo)

        plan = await svc.update_plan(str(next(iter(repo.tenants))), "professional")

        assert plan["tier"] == "pro"
        assert calls == []
        assert repo.tenants[uuid.UUID(str(next(iter(repo.tenants))))].plan_tier == "pro"

    async def test_tier_change_persists_and_emits_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        emitted: list[dict] = []

        async def _fake_emit(**kwargs) -> None:
            emitted.append(kwargs)

        monkeypatch.setattr(
            "identity.events.producers.billing_events.emit_plan_changed", _fake_emit
        )
        repo = FakeTenantRepo([_tenant(plan_tier="starter")])
        svc = _service(repo)
        tenant_id = str(next(iter(repo.tenants)))

        plan = await svc.update_plan(tenant_id, "business")

        assert plan["tier"] == "business"
        assert repo.tenants[uuid.UUID(tenant_id)].plan_tier == "business"
        assert len(emitted) == 1
        assert emitted[0]["tenant_id"] == tenant_id
        assert emitted[0]["previous_tier"] == "starter"
        assert emitted[0]["new_tier"] == "business"


class TestEffectiveTier:
    async def test_trialing_within_window_keeps_plan_tier(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(5))])
        svc = _service(repo)

        assert await svc.effective_tier(str(next(iter(repo.tenants)))) == "pro"

    async def test_expired_trial_resolves_to_free(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(-1))])
        svc = _service(repo)

        assert await svc.effective_tier(str(next(iter(repo.tenants)))) == "free"

    async def test_active_subscription_keeps_plan_tier(self) -> None:
        repo = FakeTenantRepo([_tenant(subscription_status="active")])
        svc = _service(repo)

        assert await svc.effective_tier(str(next(iter(repo.tenants)))) == "pro"

    async def test_none_and_expired_resolve_to_free(self) -> None:
        for status in ("none", "expired", "canceled"):
            repo = FakeTenantRepo([_tenant(subscription_status=status, trial_ends_at=None)])
            svc = _service(repo)

            assert await svc.effective_tier(str(next(iter(repo.tenants)))) == "free", status


class TestRequirePlanAccess:
    async def test_pass_when_tier_in_required_set(self) -> None:
        repo = FakeTenantRepo([_tenant(trial_ends_at=_trial_ends(5))])
        svc = _service(repo)

        await svc.require_plan_access(str(next(iter(repo.tenants))), ("pro", "business"))

    async def test_403_when_tier_too_low_but_active(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    plan_tier="starter",
                    subscription_status="trialing",
                    trial_ends_at=_trial_ends(5),
                )
            ]
        )
        svc = _service(repo)

        with pytest.raises(PermissionDeniedError):
            await svc.require_plan_access(str(next(iter(repo.tenants))), ("enterprise",))

    async def test_402_when_no_active_subscription(self) -> None:
        repo = FakeTenantRepo([_tenant(plan_tier="business", trial_ends_at=_trial_ends(-1))])
        svc = _service(repo)

        with pytest.raises(PaymentRequiredError):
            await svc.require_plan_access(str(next(iter(repo.tenants))), ("business", "enterprise"))


def _stripe_status_object(
    *, subscription_id: str = "sub_789", customer_id: str = "cus_123", status: str = "active"
) -> dict:
    return {"id": subscription_id, "customer": customer_id, "status": status}


class TestStripeWebhookLifecycle:
    """Webhook dispatcher: tenant resolution, idempotency, state transitions."""

    NOW = datetime(2026, 1, 10, tzinfo=UTC)

    async def _handle(
        self,
        svc: BillingService,
        *,
        event_id: str,
        event_type: str,
        event_object: dict,
    ) -> str:
        return await svc.handle_stripe_event(
            event_id=event_id, event_type=event_type, event_object=event_object
        )

    async def test_checkout_stores_stripe_ids_and_activates(self) -> None:
        repo = FakeTenantRepo([_tenant(subscription_status="trialing")])
        audit = FakeAuditService()
        svc = _service(repo, now=self.NOW, audit=audit)
        tid = str(next(iter(repo.tenants)))

        status = await self._handle(
            svc,
            event_id="evt_checkout_1",
            event_type="checkout.session.completed",
            event_object={
                "client_reference_id": tid,
                "customer": "cus_123",
                "subscription": "sub_789",
                "customer_details": {"email": "billing@acme.io"},
            },
        )

        tenant = repo.tenants[uuid.UUID(tid)]
        assert status == "applied"
        assert tenant.subscription_status == "active"
        assert tenant.stripe_customer_id == "cus_123"
        assert tenant.stripe_subscription_id == "sub_789"
        assert tenant.billing_email == "billing@acme.io"
        assert [e["action"] for e in audit.entries] == ["billing.checkout.completed"]

    async def test_checkout_unknown_tenant_consumed_without_error(self) -> None:
        repo = FakeTenantRepo()
        svc = _service(repo, now=self.NOW)

        status = await self._handle(
            svc,
            event_id="evt_checkout_orphan",
            event_type="checkout.session.completed",
            event_object={"client_reference_id": str(uuid.uuid4()), "customer": "cus_x"},
        )

        assert status == "applied"
        assert "evt_checkout_orphan" in repo.processed_events

    async def test_unknown_event_type_is_ignored_and_acknowledged(self) -> None:
        repo = FakeTenantRepo()
        svc = _service(repo, now=self.NOW)

        status = await self._handle(
            svc,
            event_id="evt_invoice_1",
            event_type="invoice.payment_succeeded",
            event_object={"customer": "cus_x"},
        )

        assert status == "ignored"
        assert "evt_invoice_1" in repo.processed_events

    async def test_subscription_updated_to_past_due_starts_grace_clock(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    subscription_status="active",
                    stripe_customer_id="cus_123",
                    stripe_subscription_id="sub_789",
                )
            ]
        )
        audit = FakeAuditService()
        svc = _service(repo, now=self.NOW, audit=audit)
        tid = str(next(iter(repo.tenants)))

        status = await self._handle(
            svc,
            event_id="evt_update_1",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(status="past_due"),
        )

        tenant = repo.tenants[uuid.UUID(tid)]
        assert status == "applied"
        assert tenant.subscription_status == "past_due"
        assert tenant.grace_started_at == self.NOW
        assert [e["action"] for e in audit.entries] == [
            "billing.subscription.updated",
            "billing.grace.started",
        ]

    async def test_past_due_replay_keeps_grace_clock_immovable(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    subscription_status="past_due",
                    grace_started_at=self.NOW,
                    stripe_customer_id="cus_123",
                )
            ]
        )
        audit = FakeAuditService()
        svc = _service(repo, now=self.NOW + timedelta(hours=1), audit=audit)
        tid = str(next(iter(repo.tenants)))

        await self._handle(
            svc,
            event_id="evt_update_again",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(status="past_due"),
        )

        tenant = repo.tenants[uuid.UUID(tid)]
        assert tenant.subscription_status == "past_due"
        assert tenant.grace_started_at == self.NOW

    async def test_past_due_active_then_past_due_starts_fresh_clock(self) -> None:
        repo = FakeTenantRepo([_tenant(subscription_status="active", stripe_customer_id="cus_123")])
        tid = str(next(iter(repo.tenants)))
        later = self.NOW + timedelta(days=1)

        await self._handle(
            _service(repo, now=self.NOW),
            event_id="evt_a",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(status="past_due"),
        )
        assert repo.tenants[uuid.UUID(tid)].grace_started_at == self.NOW

        await self._handle(
            _service(repo, now=self.NOW),
            event_id="evt_b",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(status="active"),
        )
        assert repo.tenants[uuid.UUID(tid)].grace_started_at is None

        await self._handle(
            _service(repo, now=later),
            event_id="evt_c",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(status="past_due"),
        )
        tenant = repo.tenants[uuid.UUID(tid)]
        assert tenant.grace_started_at == later

    async def test_subscription_updated_active_clears_grace_clock(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    subscription_status="past_due",
                    grace_started_at=self.NOW,
                    stripe_customer_id="cus_123",
                )
            ]
        )
        svc = _service(repo, now=self.NOW)
        tid = str(next(iter(repo.tenants)))

        await self._handle(
            svc,
            event_id="evt_recovered",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(),
        )

        tenant = repo.tenants[uuid.UUID(tid)]
        assert tenant.subscription_status == "active"
        assert tenant.grace_started_at is None

    async def test_subscription_deleted_downgrades_to_free(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    plan_tier="business",
                    subscription_status="active",
                    stripe_customer_id="cus_123",
                    stripe_subscription_id="sub_789",
                )
            ]
        )
        audit = FakeAuditService()
        svc = _service(repo, now=self.NOW, audit=audit)
        tid = str(next(iter(repo.tenants)))

        status = await self._handle(
            svc,
            event_id="evt_deleted_1",
            event_type="customer.subscription.deleted",
            event_object=_stripe_status_object(status="canceled"),
        )

        tenant = repo.tenants[uuid.UUID(tid)]
        assert status == "applied"
        assert tenant.plan_tier == "free"
        assert tenant.subscription_status == "free"
        assert tenant.grace_started_at is None
        assert [e["action"] for e in audit.entries] == [
            "billing.subscription.deleted",
            "billing.downgraded",
        ]

    async def test_subscription_updated_unmatched_tenant_consumed(self) -> None:
        svc = _service(FakeTenantRepo(), now=self.NOW)

        status = await self._handle(
            svc,
            event_id="evt_unknown_tenant",
            event_type="customer.subscription.updated",
            event_object=_stripe_status_object(),
        )

        assert status == "applied"

    async def test_duplicate_event_is_skipped_and_not_reaudited(self) -> None:
        repo = FakeTenantRepo([_tenant(subscription_status="trialing")])
        audit = FakeAuditService()
        svc = _service(repo, now=self.NOW, audit=audit)
        tid = str(next(iter(repo.tenants)))
        event_object = {
            "client_reference_id": tid,
            "customer": "cus_123",
            "subscription": "sub_789",
        }

        first = await self._handle(
            svc,
            event_id="evt_dup",
            event_type="checkout.session.completed",
            event_object=event_object,
        )
        second = await self._handle(
            svc,
            event_id="evt_dup",
            event_type="checkout.session.completed",
            event_object=event_object,
        )

        assert first == "applied"
        assert second == "skipped"
        assert [e["action"] for e in audit.entries] == ["billing.checkout.completed"]


class TestGracePeriod:
    """Soft downgrade keeps paid access inside the window, drops it after."""

    NOW = datetime(2026, 1, 10, tzinfo=UTC)

    async def test_past_due_within_grace_keeps_plan_tier(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    plan_tier="pro",
                    subscription_status="past_due",
                    grace_started_at=self.NOW - timedelta(days=3),
                )
            ]
        )
        svc = _service(repo, now=self.NOW)
        tid = str(next(iter(repo.tenants)))

        assert await svc.effective_tier(tid) == "pro"
        assert repo.grace_flips == []
        assert repo.tenants[uuid.UUID(tid)].plan_tier == "pro"

    async def test_grace_expired_downgrades_to_free_lazily(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    plan_tier="pro",
                    subscription_status="past_due",
                    grace_started_at=self.NOW - timedelta(days=8),
                )
            ]
        )
        audit = FakeAuditService()
        svc = _service(repo, now=self.NOW, audit=audit)
        tid = str(next(iter(repo.tenants)))

        sub = await svc.refresh_subscription(tid)

        assert sub.plan_tier == "free"
        assert sub.subscription_status == "free"
        assert sub.grace_started_at is None
        assert repo.grace_flips == [uuid.UUID(tid)]
        assert [e["action"] for e in audit.entries] == ["billing.downgraded"]
        assert audit.entries[0]["details"]["reason"] == "grace_expired"
        assert await svc.effective_tier(tid) == "free"


class TestTick:
    """Explicit lazy-check trigger reports change without a scheduled timer."""

    NOW = datetime(2026, 1, 10, tzinfo=UTC)

    async def test_healthy_tenant_reports_no_change(self) -> None:
        repo = FakeTenantRepo([_tenant(subscription_status="active")])
        svc = _service(repo, now=self.NOW)
        tid = str(next(iter(repo.tenants)))

        result = await svc.tick(tid)

        assert result == {"tenant_id": tid, "checked": True, "changed": False}

    async def test_expired_grace_tick_reports_change_and_downgrades(self) -> None:
        repo = FakeTenantRepo(
            [
                _tenant(
                    plan_tier="pro",
                    subscription_status="past_due",
                    grace_started_at=self.NOW - timedelta(days=8),
                )
            ]
        )
        svc = _service(repo, now=self.NOW)
        tid = str(next(iter(repo.tenants)))

        result = await svc.tick(tid)

        assert result == {"tenant_id": tid, "checked": True, "changed": True}
        assert repo.tenants[uuid.UUID(tid)].subscription_status == "free"


class TestCheckoutSession:
    """create_checkout_session: validation, lazy customer, session creation."""

    async def test_creates_customer_and_session_for_paid_plan(self) -> None:
        repo = FakeTenantRepo([_tenant(billing_email="billing@acme.io")])
        audit = FakeAuditService()
        stripe = FakeStripeClient()
        svc = _service(repo, audit=audit, stripe=stripe)
        tid = str(next(iter(repo.tenants)))

        result = await svc.create_checkout_session(tid, "professional", "month")

        tenant = repo.tenants[uuid.UUID(tid)]
        assert result["session_id"].startswith("cs_")
        assert result["url"].startswith("https://checkout.stripe.com/")
        assert tenant.stripe_customer_id == "cus_1"
        assert stripe.created_customers[0]["email"] == "billing@acme.io"
        assert stripe.created_customers[0]["metadata"]["tenant_id"] == tid
        session = stripe.created_checkout_sessions[0]
        assert session["customer_id"] == "cus_1"
        assert session["price_id"] == "price_pro_month"
        assert session["client_reference_id"] == tid
        assert session["metadata"] == {
            "tenant_id": tid,
            "plan_id": "professional",
            "interval": "month",
        }
        assert session["success_url"].endswith("/dashboard/settings/billing?checkout=success")
        assert session["cancel_url"].endswith("/dashboard/settings/billing?checkout=cancelled")
        assert [e["action"] for e in audit.entries] == ["billing.checkout.created"]
        assert audit.entries[0]["details"]["plan_id"] == "professional"

    async def test_reuses_existing_stripe_customer(self) -> None:
        repo = FakeTenantRepo([_tenant(stripe_customer_id="cus_existing")])
        stripe = FakeStripeClient()
        svc = _service(repo, stripe=stripe)
        tid = str(next(iter(repo.tenants)))

        result = await svc.create_checkout_session(tid, "professional", "month")

        assert stripe.created_customers == []
        assert result["session_id"].startswith("cs_")
        assert stripe.created_checkout_sessions[0]["customer_id"] == "cus_existing"

    async def test_unknown_plan_raises_validation_error(self) -> None:
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=FakeStripeClient())
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ValidationError, match="Unknown plan"):
            await svc.create_checkout_session(tid, "enterprise-plus", "month")

    async def test_unknown_interval_raises_validation_error(self) -> None:
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=FakeStripeClient())
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ValidationError, match="billing interval"):
            await svc.create_checkout_session(tid, "professional", "weekly")

    async def test_plan_without_configured_price_raises_validation_error(self) -> None:
        """Starter is free and Enterprise is custom-priced - no Checkout price map entry."""
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=FakeStripeClient())
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ValidationError, match="No Stripe price"):
            await svc.create_checkout_session(tid, "enterprise", "month")

    async def test_disabled_stripe_raises_service_unavailable(self) -> None:
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=FakeStripeClient(enabled=False))
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ServiceUnavailableError, match="Stripe is not configured"):
            await svc.create_checkout_session(tid, "professional", "month")

    async def test_missing_stripe_client_raises_service_unavailable(self) -> None:
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=None)
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ServiceUnavailableError, match="Stripe is not configured"):
            await svc.create_checkout_session(tid, "professional", "month")

    async def test_missing_app_url_raises_service_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BILLING_APP_URL", "")
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=FakeStripeClient())
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ServiceUnavailableError, match="BILLING_APP_URL"):
            await svc.create_checkout_session(tid, "professional", "month")


class TestPortalSession:
    """create_portal_session: customer requirement, redirect building."""

    async def test_creates_portal_session_for_existing_customer(self) -> None:
        repo = FakeTenantRepo([_tenant(stripe_customer_id="cus_abc")])
        audit = FakeAuditService()
        stripe = FakeStripeClient()
        svc = _service(repo, audit=audit, stripe=stripe)
        tid = str(next(iter(repo.tenants)))

        result = await svc.create_portal_session(tid)

        assert result["session_id"].startswith("ps_")
        assert result["url"].startswith("https://billing.stripe.com/")
        session = stripe.created_portal_sessions[0]
        assert session["customer_id"] == "cus_abc"
        assert session["return_url"].endswith("/dashboard/settings/billing")
        assert [e["action"] for e in audit.entries] == ["billing.portal.opened"]

    async def test_no_customer_raises_payment_required(self) -> None:
        repo = FakeTenantRepo([_tenant()])
        svc = _service(repo, stripe=FakeStripeClient())
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(PaymentRequiredError, match="subscription"):
            await svc.create_portal_session(tid)

    async def test_disabled_stripe_raises_service_unavailable(self) -> None:
        repo = FakeTenantRepo([_tenant(stripe_customer_id="cus_abc")])
        svc = _service(repo, stripe=FakeStripeClient(enabled=False))
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ServiceUnavailableError, match="Stripe is not configured"):
            await svc.create_portal_session(tid)

    async def test_missing_app_url_raises_service_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BILLING_APP_URL", "")
        repo = FakeTenantRepo([_tenant(stripe_customer_id="cus_abc")])
        svc = _service(repo, stripe=FakeStripeClient())
        tid = str(next(iter(repo.tenants)))

        with pytest.raises(ServiceUnavailableError, match="BILLING_APP_URL"):
            await svc.create_portal_session(tid)
