"""Integration tests proving tenant isolation at the HTTP layer.

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

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from identity.core.security import create_access_token, verify_jwt
from identity.core.tenant_context import TenantContext
from identity.db.session import async_session_factory
from identity.models.user import UserModel

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
def acme_access_token(integration_db: dict[str, str]) -> str:
    """A valid access token for alice@acme.io bound to the acme tenant."""
    return create_access_token(
        subject=integration_db["user_a_id"],
        tenant_id=integration_db["acme_id"],
    )


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
    """login/register issue tokens bound to the routed tenant."""

    async def test_login_issues_token_bound_to_routed_tenant(
        self, client: AsyncClient, integration_db: dict[str, str]
    ) -> None:
        email = f"tenant-bound-{uuid.uuid4().hex[:8]}@acme.io"
        try:
            register = await client.post(
                "/api/v1/auth/register",
                headers={"X-Tenant-Slug": "acme"},
                json={
                    "email": email,
                    "password": "TestPassword123!",
                    "full_name": "Tenant Bound",
                },
            )
            assert register.status_code == 200
            register_token = register.json()["data"]["access_token"]

            login = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": "acme"},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert login.status_code == 200
            login_token = login.json()["data"]["access_token"]
        finally:
            # Remove only the rows this test created (sessions cascade).
            async with async_session_factory() as session:
                await session.execute(delete(UserModel).where(UserModel.email == email))
                await session.commit()

        for token in (register_token, login_token):
            claims = verify_jwt(token)
            assert claims["tenant_id"] == integration_db["acme_id"]
            assert claims["type"] == "access"
