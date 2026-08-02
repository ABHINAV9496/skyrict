"""Integration tests for auth endpoints."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

# Every non-skipped request must route through a tenant (X-Tenant-Slug in dev);
# the autouse ``integration_db`` fixture skips the suite when Postgres is down.
_HEADERS = {"X-Tenant-Slug": "acme"}


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
        response = await client.post("/api/v1/auth/register", headers=_HEADERS, json={})
        assert response.status_code == 422

    async def test_register_and_login(self, client: AsyncClient):
        email = f"auth-flow-{uuid.uuid4().hex[:8]}@test.com"
        register_response = await client.post(
            "/api/v1/auth/register",
            headers=_HEADERS,
            json={
                "email": email,
                "password": "TestPassword123!",
                "full_name": "Test User",
            },
        )
        assert register_response.status_code == 200

        login_response = await client.post(
            "/api/v1/auth/login",
            headers=_HEADERS,
            json={"email": email, "password": "TestPassword123!"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["data"]["access_token"]

    async def test_get_profile_unauthorized(self, client: AsyncClient):
        # Tenant resolves (acme) but there is no token -> route dependency 401.
        response = await client.get("/api/v1/users/me", headers=_HEADERS)
        assert response.status_code == 401  # No auth token

    async def test_list_sessions_unauthorized(self, client: AsyncClient):
        response = await client.get("/api/v1/sessions", headers=_HEADERS)
        assert response.status_code == 401
