"""Integration tests for the billing/trial API (SKY-35, BILLING-UI-004).

Drives the real HTTP contract end to end:
  * org provisioning starts a 14-day trial,
  * subscription/plan/catalog reads work for owner AND members,
  * plan changes are owner-only (403 for members), unknown plans 422,
  * an expired trial is lazily flips to ``expired`` (days 0) while reads
    keep working,
  * 402 payment-required maps to a problem+json response,
  * POST /billing/checkout-session and /billing/portal-session contracts:
    403 for members, 503 when Stripe is unconfigured, 422 for unknown plans,
    402 portal with no customer, 200 with a fake Stripe boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import delete, update

from identity.core.config import settings
from identity.db.session import async_session_factory
from identity.features.billing.service import BillingService
from identity.models.tenant import TenantModel
from skyrict_common.exceptions import PaymentRequiredError
from tests.integration.api.mfa_helpers import enroll_mfa_if_required
from tests.integration.api.wizard import provision_tenant, wizard_login

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _cleanup_tenant(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


async def _register_tenant(client: AsyncClient, *, plan_id: str = "professional") -> dict:
    tenant = await provision_tenant(client, plan_id=plan_id)
    creds = await wizard_login(
        client, slug=tenant["slug"], email=tenant["email"], password=tenant["password"]
    )
    return {
        "slug": tenant["slug"],
        "email": tenant["email"],
        "token": creds["token"],
        "user_id": creds["user_id"],
    }


def _owner_headers(tenant: dict) -> dict:
    return {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {tenant['token']}"}


async def _invite_and_login_member(
    client: AsyncClient, *, tenant: dict, role_name: str = "standard_user"
) -> dict:
    owner_headers = _owner_headers(tenant)
    invite_email = f"bill-member-{uuid.uuid4().hex[:8]}@test.com"
    create_resp = await client.post(
        "/api/v1/invitations",
        headers=owner_headers,
        json={"email": invite_email, "role_name": role_name},
    )
    assert create_resp.status_code == 200
    invite_token = create_resp.json()["data"]["token"]

    accept_resp = await client.post(
        "/api/v1/invitations/accept",
        headers={"X-Tenant-Slug": tenant["slug"]},
        data={
            "token": invite_token,
            "email": invite_email,
            "password": "InviteePass123!",
            "full_name": "Billing Member",
        },
    )
    assert accept_resp.status_code == 200

    login = await client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": tenant["slug"]},
        json={"email": invite_email, "password": "InviteePass123!"},
    )
    assert login.status_code == 200
    token = await enroll_mfa_if_required(
        client, slug=tenant["slug"], login_data=login.json()["data"]
    )
    return {
        "email": invite_email,
        "token": token,
        "headers": {"X-Tenant-Slug": tenant["slug"], "Authorization": f"Bearer {token}"},
    }


class TestTrialProvisioning:
    async def test_signup_sets_trial_fields(self, client: AsyncClient) -> None:
        tenant = await provision_tenant(client)
        try:
            async with async_session_factory() as session:
                row = await session.get(TenantModel, uuid.UUID(tenant["tenant_id"]))
                assert row is not None
                assert row.plan_tier == "pro"
                assert row.subscription_status == "trialing"
                assert row.trial_ends_at is not None
                expected_ends = datetime.now(UTC) + timedelta(days=settings.BILLING_TRIAL_DAYS)
                delta = abs((expected_ends - row.trial_ends_at).total_seconds())
                assert delta < 60
        finally:
            await _cleanup_tenant(tenant["slug"])


class TestSubscriptionReads:
    async def test_owner_reads_subscription_plan_and_catalog(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = _owner_headers(tenant)
        try:
            sub = await client.get("/api/v1/billing/subscription", headers=headers)
            assert sub.status_code == 200
            data = sub.json()["data"]
            assert data["plan_id"] == "professional"
            assert data["plan_tier"] == "pro"
            assert data["subscription_status"] == "trialing"
            assert data["trial_ends_at"]
            assert data["days_remaining"] == settings.BILLING_TRIAL_DAYS

            plan = await client.get("/api/v1/billing/plan", headers=headers)
            assert plan.status_code == 200
            assert plan.json()["data"]["tier"] == "pro"
            assert plan.json()["data"]["monthly_price_cents"] == 2_900

            catalog = await client.get("/api/v1/billing/plans", headers=headers)
            assert catalog.status_code == 200
            ids = [p["id"] for p in catalog.json()["data"]]
            assert ids == ["starter", "professional", "business", "enterprise"]
        finally:
            await _cleanup_tenant(tenant["slug"])


class TestMemberAccess:
    async def test_member_reads_subscription_but_cannot_manage_plan(
        self, client: AsyncClient
    ) -> None:
        tenant = await _register_tenant(client)
        member = await _invite_and_login_member(client, tenant=tenant)
        try:
            sub = await client.get("/api/v1/billing/subscription", headers=member["headers"])
            assert sub.status_code == 200
            assert sub.json()["data"]["subscription_status"] == "trialing"

            catalog = await client.get("/api/v1/billing/plans", headers=member["headers"])
            assert catalog.status_code == 200

            plan = await client.get("/api/v1/billing/plan", headers=member["headers"])
            assert plan.status_code == 403
            assert plan.json()["type"].endswith("/permission-denied")

            patch = await client.patch(
                "/api/v1/billing/plan", headers=member["headers"], json={"planId": "enterprise"}
            )
            assert patch.status_code == 403
        finally:
            await _cleanup_tenant(tenant["slug"])


class TestPlanUpdate:
    async def test_owner_changes_plan(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = _owner_headers(tenant)
        try:
            resp = await client.patch(
                "/api/v1/billing/plan", headers=headers, json={"planId": "enterprise"}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["tier"] == "enterprise"

            plan = await client.get("/api/v1/billing/plan", headers=headers)
            assert plan.json()["data"]["id"] == "enterprise"

            sub = await client.get("/api/v1/billing/subscription", headers=headers)
            assert sub.json()["data"]["plan_tier"] == "enterprise"
            assert sub.json()["data"]["subscription_status"] == "trialing"
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_unknown_plan_id_returns_422(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = _owner_headers(tenant)
        try:
            resp = await client.patch(
                "/api/v1/billing/plan", headers=headers, json={"planId": "luxury"}
            )
            assert resp.status_code == 422
            assert resp.json()["type"].endswith("/validation-error")
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_repeating_same_plan_is_idempotent(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = _owner_headers(tenant)
        try:
            first = await client.patch(
                "/api/v1/billing/plan", headers=headers, json={"planId": "professional"}
            )
            second = await client.patch(
                "/api/v1/billing/plan", headers=headers, json={"planId": "professional"}
            )
            assert first.status_code == 200
            assert second.status_code == 200
            assert first.json()["data"]["tier"] == "pro"
            assert second.json()["data"]["tier"] == "pro"
        finally:
            await _cleanup_tenant(tenant["slug"])


class TestTrialExpiry:
    async def test_expired_trial_still_readable_and_lazily_flips(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        headers = _owner_headers(tenant)
        try:
            async with async_session_factory() as session:
                await session.execute(
                    update(TenantModel)
                    .where(TenantModel.slug == tenant["slug"])
                    .values(
                        trial_ends_at=datetime.now(UTC) - timedelta(days=1),
                        subscription_status="trialing",
                    )
                )
                await session.commit()

            sub = await client.get("/api/v1/billing/subscription", headers=headers)
            assert sub.status_code == 200
            data = sub.json()["data"]
            assert data["subscription_status"] == "expired"
            assert data["days_remaining"] == 0

            plan = await client.get("/api/v1/billing/plan", headers=headers)
            assert plan.status_code == 200
            assert plan.json()["data"]["tier"] == "pro"
        finally:
            await _cleanup_tenant(tenant["slug"])


class TestPaymentRequiredMapping:
    async def test_payment_required_error_maps_to_402_problem_json(
        self, client: AsyncClient
    ) -> None:
        from identity.api.deps import get_billing_service
        from identity.main import app

        class BlockedBillingService(BillingService):
            async def get_subscription(self, tenant_id):
                raise PaymentRequiredError(
                    "An active subscription is required to access this feature"
                )

        original = get_billing_service
        app.dependency_overrides[get_billing_service] = lambda: BlockedBillingService(object())
        try:
            tenant = await provision_tenant(client)
            try:
                creds = await wizard_login(
                    client, slug=tenant["slug"], email=tenant["email"], password=tenant["password"]
                )
                headers = {
                    "X-Tenant-Slug": tenant["slug"],
                    "Authorization": f"Bearer {creds['token']}",
                }
                resp = await client.get("/api/v1/billing/subscription", headers=headers)
                assert resp.status_code == 402
                body = resp.json()
                assert body["type"].endswith("/payment-required")
                assert body["status"] == 402
            finally:
                await _cleanup_tenant(tenant["slug"])
        finally:
            app.dependency_overrides.pop(get_billing_service)
            if original is not get_billing_service:
                app.dependency_overrides[get_billing_service] = original


# ---------------------------------------------------------------------------
# POST /billing/checkout-session and /billing/portal-session contracts
# ---------------------------------------------------------------------------


class TestCheckoutSessionEndpoint:
    """Stripe Checkout session creation — owner-only, sanitized errors."""

    async def test_member_post_checkout_returns_403(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        member = await _invite_and_login_member(client, tenant=tenant)
        try:
            resp = await client.post(
                "/api/v1/billing/checkout-session",
                headers=member["headers"],
                json={"planId": "professional", "interval": "month"},
            )
            assert resp.status_code == 403
            assert resp.json()["type"].endswith("/permission-denied")
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_admin_member_post_checkout_returns_403(self, client: AsyncClient) -> None:
        """organization_admin has billing.manage but not tenant_owner: the
        role half of the owner gate must still reject the POST."""
        tenant = await _register_tenant(client)
        member = await _invite_and_login_member(
            client, tenant=tenant, role_name="organization_admin"
        )
        try:
            resp = await client.post(
                "/api/v1/billing/checkout-session",
                headers=member["headers"],
                json={"planId": "business", "interval": "year"},
            )
            assert resp.status_code == 403
            assert resp.json()["type"].endswith("/permission-denied")
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_unconfigured_stripe_returns_503(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When Stripe is disabled the endpoint returns a sanitized 503."""
        from identity.api.deps import get_stripe_client
        from identity.main import app

        # A valid price entry is needed to reach the stripe-enabled guard.
        monkeypatch.setattr(settings, "BILLING_STRIPE_PRICE_IDS", {"professional:month": "price_1"})
        app.dependency_overrides[get_stripe_client] = lambda: None  # type: ignore[func-returns-value]
        tenant = await _register_tenant(client)
        try:
            resp = await client.post(
                "/api/v1/billing/checkout-session",
                headers=_owner_headers(tenant),
                json={"planId": "professional", "interval": "month"},
            )
            assert resp.status_code == 503
            body = resp.json()
            assert body["type"].endswith("/service-unavailable")
            assert body["status"] == 503
        finally:
            app.dependency_overrides.pop(get_stripe_client, None)
            await _cleanup_tenant(tenant["slug"])

    async def test_unknown_plan_returns_422(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        try:
            resp = await client.post(
                "/api/v1/billing/checkout-session",
                headers=_owner_headers(tenant),
                json={"planId": "nonexistent", "interval": "month"},
            )
            assert resp.status_code == 422
            assert resp.json()["type"].endswith("/validation-error")
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_owner_checkout_returns_200(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from identity.api.deps import get_stripe_client
        from identity.main import app

        class _FakeStripeClient:
            enabled = True

            def create_customer(self, **_kw: Any) -> dict[str, str]:
                return {"id": "cus_fake"}

            def create_checkout_session(self, **_kw: Any) -> dict[str, str]:
                return {"id": "cs_fake", "url": "https://checkout.stripe.com/c/pay/cs_fake"}

        monkeypatch.setattr(settings, "BILLING_APP_URL", "https://{slug}.acme.test")
        monkeypatch.setattr(
            settings,
            "BILLING_STRIPE_PRICE_IDS",
            {"professional:month": "price_1"},
        )
        app.dependency_overrides[get_stripe_client] = _FakeStripeClient
        tenant = await _register_tenant(client)
        try:
            resp = await client.post(
                "/api/v1/billing/checkout-session",
                headers=_owner_headers(tenant),
                json={"planId": "professional", "interval": "month"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()["data"]
            assert body["session_id"] == "cs_fake"
            assert body["url"].startswith("https://checkout.stripe.com/")
        finally:
            app.dependency_overrides.pop(get_stripe_client, None)
            await _cleanup_tenant(tenant["slug"])


class TestPortalSessionEndpoint:
    """Stripe Customer Portal session creation — owner-only, sanitized errors."""

    async def test_member_post_portal_returns_403(self, client: AsyncClient) -> None:
        tenant = await _register_tenant(client)
        member = await _invite_and_login_member(client, tenant=tenant)
        try:
            resp = await client.post(
                "/api/v1/billing/portal-session",
                headers=member["headers"],
            )
            assert resp.status_code == 403
            assert resp.json()["type"].endswith("/permission-denied")
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_admin_member_post_portal_returns_403(self, client: AsyncClient) -> None:
        """organization_admin has billing.manage but not tenant_owner: the
        role half of the owner gate must still reject the POST."""
        tenant = await _register_tenant(client)
        member = await _invite_and_login_member(
            client, tenant=tenant, role_name="organization_admin"
        )
        try:
            resp = await client.post(
                "/api/v1/billing/portal-session",
                headers=member["headers"],
            )
            assert resp.status_code == 403
            assert resp.json()["type"].endswith("/permission-denied")
        finally:
            await _cleanup_tenant(tenant["slug"])

    async def test_no_stripe_customer_returns_402(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from identity.api.deps import get_stripe_client
        from identity.main import app

        class _FakeStripeClient:
            enabled = True

            def create_portal_session(self, **_kw: Any) -> dict[str, str]:
                return {"id": "ps_fake", "url": "https://billing.stripe.com/p/session/ps_fake"}

        monkeypatch.setattr(settings, "BILLING_APP_URL", "https://{slug}.acme.test")
        app.dependency_overrides[get_stripe_client] = _FakeStripeClient
        # A freshly provisioned tenant has no stripe_customer_id yet.
        tenant = await _register_tenant(client)
        try:
            resp = await client.post(
                "/api/v1/billing/portal-session",
                headers=_owner_headers(tenant),
            )
            assert resp.status_code == 402
            body = resp.json()
            assert body["type"].endswith("/payment-required")
            assert body["status"] == 402
        finally:
            app.dependency_overrides.pop(get_stripe_client, None)
            await _cleanup_tenant(tenant["slug"])

    async def test_disabled_stripe_returns_503(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from identity.api.deps import get_stripe_client
        from identity.main import app

        monkeypatch.setattr(settings, "BILLING_APP_URL", "https://acme.test")
        app.dependency_overrides[get_stripe_client] = lambda: None  # type: ignore[func-returns-value]
        tenant = await _register_tenant(client)
        try:
            resp = await client.post(
                "/api/v1/billing/portal-session",
                headers=_owner_headers(tenant),
            )
            assert resp.status_code == 503
            body = resp.json()
            assert body["type"].endswith("/service-unavailable")
            assert body["status"] == 503
        finally:
            app.dependency_overrides.pop(get_stripe_client, None)
            await _cleanup_tenant(tenant["slug"])
