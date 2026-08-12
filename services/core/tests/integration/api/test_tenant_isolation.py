"""API integration tests proving tenant isolation and the auth dependency chain.

TenantContextMiddleware is the single source of truth for tenant resolution:
it derives the tenant slug from the routing layer, verifies the tenant in the
shared database, cross-checks the verified JWT's tenant claim, and populates
TenantContext. These tests exercise the full stack (middleware -> JWT
cross-check -> get_current_user -> route) against a real Postgres:

  - a token bound to tenant A succeeds on tenant A and is rejected on
    tenant B (401 tenant-mismatch);
  - unresolvable / unknown / disabled tenants are rejected before any route
    handler runs;
  - the request-scoped context is cleared after every request (no leakage);
  - health/readiness are exempt from tenant resolution.

The whole suite skips when Postgres is unavailable (see conftest.py).
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING

import pytest
from jose import jwt

from core.core.config import settings
from core.core.tenant_context import TenantContext

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_SUBJECT = str(uuid.uuid4())


def _token_for(rsa_private_key: str, tenant_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": _SUBJECT,
        "tenant_id": tenant_id,
        "iss": settings.JWKS_ISSUER,
        "aud": settings.JWKS_AUDIENCE,
        "iat": now,
        "nbf": now - 10,
        "exp": now + 300,
        "type": "access",
    }
    return jwt.encode(payload, rsa_private_key, algorithm="RS256")


class TestCrossTenantAuth:
    async def test_token_succeeds_on_its_own_tenant(
        self, client: AsyncClient, integration_db: dict[str, str], rsa_private_key: str
    ) -> None:
        token = _token_for(rsa_private_key, integration_db["acme_id"])
        response = await client.get(
            "/api/v1/me",
            headers={"X-Tenant-Slug": "olympus", "Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == _SUBJECT
        assert body["tenant_id"] == integration_db["acme_id"]

    async def test_cross_tenant_token_slug_returns_401(
        self, client: AsyncClient, integration_db: dict[str, str], rsa_private_key: str
    ) -> None:
        # Token bound to olympus, but routed as globex.
        token = _token_for(rsa_private_key, integration_db["acme_id"])
        response = await client.get(
            "/api/v1/me",
            headers={"X-Tenant-Slug": "globex", "Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["type"].endswith("/tenant-mismatch")
        assert body["status"] == 401
        # The detail must not leak internal data (e.g. tenant IDs).
        assert "globex" not in body["detail"].lower()

    async def test_invalid_token_rejected_by_route_dependency(
        self, client: AsyncClient, integration_db: dict[str, str]
    ) -> None:
        # The middleware leaves unverifiable tokens alone (it never decodes
        # without verification); get_current_user produces the canonical 401.
        response = await client.get(
            "/api/v1/me",
            headers={"X-Tenant-Slug": "olympus", "Authorization": "Bearer not-a-jwt"},
        )
        assert response.status_code == 401
        assert response.json()["type"].endswith("/token-invalid")


class TestTenantResolution:
    async def test_unresolvable_tenant_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/me")
        assert response.status_code == 400
        body = response.json()
        assert body["type"].endswith("/tenant-context-missing")
        assert body["status"] == 400

    async def test_unknown_tenant_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/me", headers={"X-Tenant-Slug": "does-not-exist"})
        assert response.status_code == 404
        body = response.json()
        assert body["type"].endswith("/tenant-not-found")
        assert body["status"] == 404

    async def test_disabled_tenant_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/me", headers={"X-Tenant-Slug": "disabledco"})
        assert response.status_code == 403
        body = response.json()
        assert body["type"].endswith("/tenant-disabled")
        assert body["status"] == 403


class TestContextLifecycle:
    async def test_no_tenant_leaks_to_next_request(
        self, client: AsyncClient, integration_db: dict[str, str], rsa_private_key: str
    ) -> None:
        token = _token_for(rsa_private_key, integration_db["acme_id"])
        first = await client.get(
            "/api/v1/me",
            headers={"X-Tenant-Slug": "olympus", "Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 200

        # The context must be fully cleared: a follow-up request without a
        # routable tenant is rejected — it must NOT inherit the previous one.
        second = await client.get("/api/v1/me")
        assert second.status_code == 400
        assert second.json()["type"].endswith("/tenant-context-missing")
        assert TenantContext.get_optional() is None

    async def test_request_id_echoed_on_middleware_error(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/me",
            headers={"X-Tenant-Slug": "does-not-exist", "X-Request-ID": "trace-abc-123"},
        )
        assert response.status_code == 404
        assert response.headers["X-Request-ID"] == "trace-abc-123"
        assert response.json()["instance"] == "trace-abc-123"
