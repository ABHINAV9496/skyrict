"""Unit tests for the billing service (SKY-35) with a fake persistent repo.

Covers subscription reads, the lazy trial-expiry flip, plan updates, the plan
gate matrix (403 vs 402), and no-op/idempotent behaviour.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.domain.entities import Tenant
from identity.features.billing.plans import resolve_plan_id
from identity.features.billing.service import BillingService
from skyrict_common.exceptions import (
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
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

    async def get_by_id(self, tenant_id: str | uuid.UUID) -> Tenant | None:
        return self.tenants.get(uuid.UUID(str(tenant_id)))

    async def update_billing(
        self,
        tenant_id: str | uuid.UUID,
        *,
        plan_tier: str | None = None,
        subscription_status: str | None = None,
        trial_ends_at: datetime | None = None,
    ) -> Tenant:
        tenant = self.tenants[uuid.UUID(str(tenant_id))]
        if plan_tier is not None:
            tenant.plan_tier = plan_tier
        if subscription_status is not None:
            tenant.subscription_status = subscription_status
        if trial_ends_at is not None:
            tenant.trial_ends_at = trial_ends_at
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


def _tenant(
    *,
    plan_tier: str = "pro",
    subscription_status: str = "trialing",
    trial_ends_at: datetime | None = None,
) -> Tenant:
    return Tenant(
        name="Acme",
        slug="acme",
        plan_tier=plan_tier,
        subscription_status=subscription_status,
        trial_ends_at=trial_ends_at,
    )


def _service(repo: FakeTenantRepo, now: datetime | None = None) -> BillingService:
    return BillingService(repo, now=now)


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
        for status in ("none", "expired", "canceled", "past_due"):
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
