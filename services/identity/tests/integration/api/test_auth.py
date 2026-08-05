"""Integration tests for auth endpoints."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from identity.core.config import settings
from identity.db.session import async_session_factory
from identity.models.tenant import TenantModel

if TYPE_CHECKING:
    from httpx import AsyncClient

# Business routes must route through a tenant (X-Tenant-Slug in dev); the
# autouse ``integration_db`` fixture skips the suite when Postgres is down.
# Self-service /auth/register and /auth/verify-email bypass tenant resolution.
_HEADERS = {"X-Tenant-Slug": "acme"}


async def _delete_tenant_by_slug(slug: str) -> None:
    """Remove a tenant provisioned by a test (cascades to users/roles/grants)."""
    async with async_session_factory() as session:
        await session.execute(delete(TenantModel).where(TenantModel.slug == slug))
        await session.commit()


@pytest.mark.integration
class TestAuthEndpoints:
    """Test auth API endpoints with a real test database."""

    async def test_health_check(self, client: AsyncClient):
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    async def test_readiness_check(self, client: AsyncClient):
        response = await client.get("/api/v1/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"

    async def test_login_missing_fields(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/login", headers=_HEADERS, json={})
        assert response.status_code == 422  # Validation error

    async def test_register_missing_fields(self, client: AsyncClient):
        response = await client.post("/api/v1/auth/register", json={})
        assert response.status_code == 422

    async def test_register_verify_and_login(self, client: AsyncClient):
        email = f"auth-flow-{uuid.uuid4().hex[:8]}@test.com"
        org = f"Auth Flow {uuid.uuid4().hex[:8]}"
        register_response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "TestPassword123!",
                "full_name": "Test User",
                "organization_name": org,
            },
        )
        assert register_response.status_code == 200
        data = register_response.json()["data"]
        assert data["verification_pending"] is True
        assert data["verification_token"]
        slug = data["tenant_slug"]

        try:
            # Unverified accounts are blocked at login (403 email-not-verified).
            blocked = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert blocked.status_code == 403
            assert blocked.json()["type"].endswith("/email-not-verified")

            verify_response = await client.post(
                "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
            )
            assert verify_response.status_code == 200

            login_response = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert login_response.status_code == 200
            assert login_response.json()["data"]["access_token"]
        finally:
            await _delete_tenant_by_slug(slug)

    async def test_get_profile_unauthorized(self, client: AsyncClient):
        # Tenant resolves (acme) but there is no token -> route dependency 401.
        response = await client.get("/api/v1/users/me", headers=_HEADERS)
        assert response.status_code == 401  # No auth token

    async def test_list_sessions_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/v1/sessions", headers=_HEADERS)
        assert response.status_code == 401


class TestLoginRateLimit:
    """POST /auth/login is rate-limited per (source IP, account).

    Blunts brute-force / credential-stuffing on the highest-value endpoint
    (Redis fixed-window; the limiter fails open on infra errors). The first
    ``RATE_LIMIT_LOGIN`` attempts are rejected as auth failures; the next
    attempt in the same window is a 429.
    """

    async def test_sixth_attempt_in_window_is_rate_limited(self, client: AsyncClient) -> None:
        email = f"rl-{uuid.uuid4().hex[:8]}@acme.io"
        for _ in range(settings.RATE_LIMIT_LOGIN):
            resp = await client.post(
                "/api/v1/auth/login",
                headers=_HEADERS,
                json={"email": email, "password": "WrongPass1!"},
            )
            assert resp.status_code >= 400, (
                f"attempt {_ + 1} expected rejected, got {resp.status_code}"
            )

        blocked = await client.post(
            "/api/v1/auth/login",
            headers=_HEADERS,
            json={"email": email, "password": "WrongPass1!"},
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["type"].endswith("/rate-limit-exceeded")
        assert body["status"] == 429
        # The 429 must not hint at the account's existence either.
        assert "not found" not in body["detail"].lower()
