"""Integration tests for auth endpoints."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import delete

from identity.core.config import settings
from identity.core.constants import LOGIN_FAILED_MESSAGE
from identity.core.security import hash_password
from identity.db.session import async_session_factory
from identity.models.tenant import TenantModel
from identity.models.user import UserModel

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
            # Unverified accounts are blocked at login with the uniform 401 —
            # indistinguishable from any other failure (anti-enumeration).
            blocked = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            assert blocked.status_code == 401
            assert blocked.json()["type"].endswith("/authentication-error")
            assert blocked.json()["detail"] == LOGIN_FAILED_MESSAGE

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


class TestLoginAntiEnumeration:
    """Every login failure returns the identical RFC 7807 401 response.

    Unknown email, wrong password, unverified, and disabled accounts are
    indistinguishable at the API layer (status code, problem type, and
    detail) — the backend is the source of truth; the frontend guides
    account recovery via account-level state (SKY-21), never via backend
    error semantics.
    """

    def _assert_uniform_failure(self, response) -> None:
        assert response.status_code == 401
        body = response.json()
        assert body["type"].endswith("/authentication-error")
        assert body["status"] == 401
        assert body["detail"] == LOGIN_FAILED_MESSAGE

    async def test_unknown_email_is_indistinguishable(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            headers=_HEADERS,
            json={
                "email": f"nobody-{uuid.uuid4().hex[:8]}@acme.io",
                "password": "WrongPass1!",
            },
        )
        self._assert_uniform_failure(resp)

    async def test_wrong_password_is_indistinguishable(self, client: AsyncClient) -> None:
        email = f"enum-pw-{uuid.uuid4().hex[:8]}@test.com"
        register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "TestPassword123!",
                "full_name": "Enum Pw",
                "organization_name": f"Enum Pw Corp {uuid.uuid4().hex[:8]}",
            },
        )
        assert register.status_code == 200
        data = register.json()["data"]
        slug = data["tenant_slug"]
        try:
            verify = await client.post(
                "/api/v1/auth/verify-email", json={"token": data["verification_token"]}
            )
            assert verify.status_code == 200

            resp = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "WrongPass1!"},
            )
            self._assert_uniform_failure(resp)
        finally:
            await _delete_tenant_by_slug(slug)

    async def test_unverified_account_is_indistinguishable(self, client: AsyncClient) -> None:
        email = f"enum-uv-{uuid.uuid4().hex[:8]}@test.com"
        register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "TestPassword123!",
                "full_name": "Enum Uv",
                "organization_name": f"Enum Uv Corp {uuid.uuid4().hex[:8]}",
            },
        )
        assert register.status_code == 200
        data = register.json()["data"]
        slug = data["tenant_slug"]
        try:
            # Correct password, but the account was never verified — the
            # response must look exactly like a wrong-password failure.
            resp = await client.post(
                "/api/v1/auth/login",
                headers={"X-Tenant-Slug": slug},
                json={"email": email, "password": "TestPassword123!"},
            )
            self._assert_uniform_failure(resp)
        finally:
            await _delete_tenant_by_slug(slug)

    async def test_disabled_account_is_indistinguishable(
        self, client: AsyncClient, integration_db: dict[str, str]
    ) -> None:
        email = f"disabled-{uuid.uuid4().hex[:8]}@acme.io"
        user_id = uuid.uuid4()
        async with async_session_factory() as session:
            session.add(
                UserModel(
                    id=user_id,
                    tenant_id=integration_db["acme_id"],
                    email=email,
                    password_hash=hash_password("TestPassword123!"),
                    full_name="Disabled Enum",
                    is_active=False,
                    is_verified=True,
                )
            )
            await session.commit()
        try:
            resp = await client.post(
                "/api/v1/auth/login",
                headers=_HEADERS,
                json={"email": email, "password": "TestPassword123!"},
            )
            self._assert_uniform_failure(resp)
        finally:
            async with async_session_factory() as session:
                await session.execute(delete(UserModel).where(UserModel.id == user_id))
                await session.commit()
