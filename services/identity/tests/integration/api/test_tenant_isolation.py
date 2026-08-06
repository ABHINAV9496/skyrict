"""
Integration tests proving tenant isolation at the HTTP layer.

TenantContextMiddleware is the single source of truth for tenant resolution:
it derives the tenant slug from the routing layer, verifies the tenant in the
database, cross-checks the verified JWT's tenant claim, and populates
TenantContext. These tests exercise the full stack (middleware -> JWT
cross-check -> route dependencies -> database) against a real Postgres:

  - a token bound to tenant A succeeds on tenant A and is rejected on
    tenant B (401 tenant-mismatch);
  - unresolvable / unknown / disabled tenants are rejected before any route
    handler runs;
  - the request-scoped context is cleared after every request (no leakage);
  - tokens issued by login/register carry the routed tenant's ID.

The whole suite skips when Postgres is unavailable (see conftest.py).
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from identity.core.security import create_access_token, verify_jwt
from identity.core.tenant_context import TenantContext
from identity.db.session import async_session_factory
from identity.models.tenant import TenantModel
from tests.integration.api.wizard import provision_tenant, wizard_login

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _register_and_login(client: AsyncClient) -> dict:
    """Provision a brand-new tenant via the wizard and return owner credentials."""
    tenant = await provision_tenant(client)
    creds = await wizard_login(
        client, slug=tenant["slug"], email=tenant["email"], password=tenant["password"]
    )
    return {
        "slug": tenant["slug"],
        "tenant_id": tenant["tenant_id"],
        "email": tenant["email"],
        "user_id": creds["user_id"],
        "token": creds["token"],
        "refresh_token": creds["refresh_token"],
    }


async def _delete_tenant_by_slug(slug: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


async def _delete_tenant_by_id(tenant_id: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.id == uuid.UUID(tenant_id)))
        await session.commit()


@pytest.fixture
def acme_access_token(integration_db: dict[str, str]) -> str:
    """A valid access token for alice@acme.io bound to the acme tenant."""
    return create_access_token(
        subject=integration_db["user_a_id"],
        tenant_id=integration_db["acme_id"],
    )


class TestTwoRealTenants:
    """
    Two real signup tenants: every bearer-gated endpoint rejects a token from
    the other tenant (401 tenant-mismatch) while succeeding on its own.
    """

    async def test_full_endpoint_sweep_rejects_cross_tenant(self, client: AsyncClient) -> None:
        tenant_a = await _register_and_login(client)
        tenant_b = await _register_and_login(client)
        extra_orgs: list[str] = []
        try:
            headers_a = {
                "X-Tenant-Slug": tenant_a["slug"],
                "Authorization": f"Bearer {tenant_a['token']}",
            }

            role = await client.post(
                "/api/v1/roles",
                headers=headers_a,
                json={
                    "name": f"iso-role-{uuid.uuid4().hex[:8]}",
                    "permission_keys": ["roles:read"],
                },
            )
            assert role.status_code == 200
            role_id = role.json()["data"]["id"]

            sessions = await client.get("/api/v1/sessions", headers=headers_a)
            assert sessions.status_code == 200
            session_id = sessions.json()["data"]["sessions"][0]["id"]

            invitation = await client.post(
                "/api/v1/invitations",
                headers=headers_a,
                json={
                    "email": f"iso-inv-{uuid.uuid4().hex[:8]}@test.com",
                    "role_name": "standard_user",
                },
            )
            assert invitation.status_code == 200
            invitation_id = invitation.json()["data"]["id"]

            specs: list[tuple[str, str, dict | None]] = [
                ("GET", "/api/v1/users/me", None),
                ("PUT", "/api/v1/users/me", {"full_name": "Updated Name"}),
                (
                    "POST",
                    "/api/v1/users/me/password",
                    {
                        "current_password": "TestPassword123!",
                        "new_password": "NewPassword123!",
                    },
                ),
                ("GET", "/api/v1/organizations/me", None),
                (
                    "POST",
                    "/api/v1/auth/introspect",
                    {"refresh_token": tenant_a["refresh_token"]},
                ),
                ("GET", "/api/v1/sessions", None),
                ("DELETE", f"/api/v1/sessions/{session_id}", None),
                ("DELETE", "/api/v1/sessions", None),
                ("GET", "/api/v1/roles", None),
                (
                    "POST",
                    "/api/v1/roles",
                    {
                        "name": f"iso-role-2-{uuid.uuid4().hex[:8]}",
                        "permission_keys": ["roles:read"],
                    },
                ),
                (
                    "PATCH",
                    f"/api/v1/roles/{role_id}",
                    {"name": f"iso-renamed-{uuid.uuid4().hex[:8]}"},
                ),
                (
                    "POST",
                    f"/api/v1/roles/{role_id}/assign",
                    {"user_id": tenant_a["user_id"], "scope_type": "tenant"},
                ),
                ("DELETE", f"/api/v1/roles/{role_id}", None),
                ("GET", "/api/v1/permissions", None),
                (
                    "POST",
                    "/api/v1/invitations",
                    {
                        "email": f"iso-inv-2-{uuid.uuid4().hex[:8]}@test.com",
                        "role_name": "standard_user",
                    },
                ),
                ("POST", f"/api/v1/invitations/{invitation_id}/expire", None),
            ]

            for method, path, body in specs:
                own = await client.request(method, path, headers=headers_a, json=body)
                assert own.status_code == 200, (
                    f"{method} {path} own-tenant -> {own.status_code} {own.text[:300]}"
                )
                for slug, token, direction in (
                    (tenant_b["slug"], tenant_a["token"], "A->B"),
                    (tenant_a["slug"], tenant_b["token"], "B->A"),
                ):
                    blocked = await client.request(
                        method,
                        path,
                        headers={
                            "X-Tenant-Slug": slug,
                            "Authorization": f"Bearer {token}",
                        },
                        json=body,
                    )
                    assert blocked.status_code == 401, (
                        f"{method} {path} ({direction}) -> "
                        f"{blocked.status_code} {blocked.text[:300]}"
                    )
                    assert blocked.json()["type"].endswith("/tenant-mismatch")

            org = await client.post(
                "/api/v1/organizations",
                headers=headers_a,
                json={
                    "name": f"Isolation Org {uuid.uuid4().hex[:8]}",
                    "slug": f"iso-org-{uuid.uuid4().hex[:8]}",
                },
            )
            assert org.status_code == 200
            extra_orgs.append(org.json()["data"]["id"])
            for slug, token in (
                (tenant_b["slug"], tenant_a["token"]),
                (tenant_a["slug"], tenant_b["token"]),
            ):
                blocked = await client.post(
                    "/api/v1/organizations",
                    headers={
                        "X-Tenant-Slug": slug,
                        "Authorization": f"Bearer {token}",
                    },
                    json={"name": "Sneaky Org", "slug": f"sneaky-{uuid.uuid4().hex[:8]}"},
                )
                assert blocked.status_code == 401
                assert blocked.json()["type"].endswith("/tenant-mismatch")

            relogin = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": tenant_a["slug"]},
                json={"email": tenant_a["email"], "password": "NewPassword123!"},
            )
            assert relogin.status_code == 200
            fresh_refresh = relogin.json()["data"]["refresh_token"]
            own_logout = await client.post(
                "/api/v1/auth/logout",
                headers=headers_a,
                json={"refresh_token": fresh_refresh},
            )
            assert own_logout.status_code == 200
            for slug, token in (
                (tenant_b["slug"], tenant_a["token"]),
                (tenant_a["slug"], tenant_b["token"]),
            ):
                blocked = await client.post(
                    "/api/v1/auth/logout",
                    headers={
                        "X-Tenant-Slug": slug,
                        "Authorization": f"Bearer {token}",
                    },
                    json={"refresh_token": fresh_refresh},
                )
                assert blocked.status_code == 401
                assert blocked.json()["type"].endswith("/tenant-mismatch")
        finally:
            with contextlib.suppress(Exception):
                await _delete_tenant_by_slug(tenant_a["slug"])
                await _delete_tenant_by_slug(tenant_b["slug"])
                for org_id in extra_orgs:
                    await _delete_tenant_by_id(org_id)


class TestTenantIsolation:
    """JWT-vs-routed-tenant cross-check is enforced on every request."""

    async def test_token_succeeds_on_its_own_tenant(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        acme_access_token: str,
    ) -> None:
        response = await client.get(
            "/api/v1/users/me",
            headers={"X-Tenant-Slug": "acme", "Authorization": f"Bearer {acme_access_token}"},
        )
        assert response.status_code == 200
        assert response.json()["data"]["email"] == "alice@acme.io"

    async def test_token_rejected_on_other_tenant(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        acme_access_token: str,
    ) -> None:
        response = await client.get(
            "/api/v1/users/me",
            headers={"X-Tenant-Slug": "globex", "Authorization": f"Bearer {acme_access_token}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["type"].endswith("/tenant-mismatch")
        assert body["status"] == 401
        # The detail must not leak internal data (e.g. tenant IDs).
        assert "globex" not in body["detail"].lower()


class TestTenantResolution:
    """Routing failures are rejected before any route handler runs."""

    async def test_unresolvable_tenant_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/users/me")
        assert response.status_code == 400
        body = response.json()
        assert body["type"].endswith("/tenant-context-missing")
        assert body["status"] == 400

    async def test_unknown_tenant_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/users/me", headers={"X-Tenant-Slug": "does-not-exist"})
        assert response.status_code == 404
        body = response.json()
        assert body["type"].endswith("/tenant-not-found")
        assert body["status"] == 404

    async def test_disabled_tenant_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/users/me", headers={"X-Tenant-Slug": "disabledco"})
        assert response.status_code == 403
        body = response.json()
        assert body["type"].endswith("/tenant-disabled")
        assert body["status"] == 403

    async def test_invalid_token_rejected_by_route_dependency(self, client: AsyncClient) -> None:
        # The middleware leaves unverifiable tokens alone (it never decodes
        # without verification); the route dependency produces the canonical
        # 401 problem response.
        response = await client.get(
            "/api/v1/users/me",
            headers={"X-Tenant-Slug": "acme", "Authorization": "Bearer not-a-jwt"},
        )
        assert response.status_code == 401
        assert response.json()["type"].endswith("/token-invalid")


class TestContextLifecycle:
    """The request-scoped context is cleared so no tenant leaks between requests."""

    async def test_no_tenant_leaks_to_next_request(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        acme_access_token: str,
    ) -> None:
        # First request resolves acme and succeeds.
        first = await client.get(
            "/api/v1/users/me",
            headers={"X-Tenant-Slug": "acme", "Authorization": f"Bearer {acme_access_token}"},
        )
        assert first.status_code == 200

        # The context must be fully cleared: a follow-up request without a
        # routable tenant is rejected as unresolved — it must NOT inherit the
        # previous request's tenant.
        second = await client.get("/api/v1/users/me")
        assert second.status_code == 400
        assert second.json()["type"].endswith("/tenant-context-missing")
        assert TenantContext.get_optional() is None

    async def test_request_id_echoed_on_middleware_error(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/users/me",
            headers={"X-Tenant-Slug": "does-not-exist", "X-Request-ID": "trace-abc-123"},
        )
        assert response.status_code == 404
        assert response.headers["X-Request-ID"] == "trace-abc-123"
        # Middleware errors carry the same instance (request_id) per RFC 7807.
        assert response.json()["instance"] == "trace-abc-123"

    async def test_generated_request_id_present(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/users/me", headers={"X-Tenant-Slug": "does-not-exist"})
        assert response.status_code == 404
        assert response.headers.get("X-Request-ID")
        assert response.json()["instance"] == response.headers["X-Request-ID"]


class TestTokenBinding:
    """login issues tokens bound to the routed tenant."""

    async def test_login_issues_token_bound_to_routed_tenant(
        self, client: AsyncClient, integration_db: dict[str, str]
    ) -> None:
        tenant = await provision_tenant(client)
        creds = await wizard_login(
            client, slug=tenant["slug"], email=tenant["email"], password=tenant["password"]
        )
        login_token = creds["token"]
        reg_tenant_id = tenant["tenant_id"]

        # Remove only the rows this test created (tenant cascades).
        async with async_session_factory() as session:
            await session.execute(delete(TenantModel).where(TenantModel.slug == tenant["slug"]))
            await session.commit()

        claims = verify_jwt(login_token)
        assert claims["tenant_id"] == reg_tenant_id
        assert claims["type"] == "access"
