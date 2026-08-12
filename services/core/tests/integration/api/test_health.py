"""Health/readiness integration tests — /health and /ready return 200.

The ``client`` fixture runs the real lifespan, which performs startup
dependency verification (DB SELECT 1 + JWT public key check) and opens the
readiness gate — so a green test proves the service boots end-to-end against
real Postgres.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

pytestmark = pytest.mark.integration


class TestHealth:
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert body["service"] == "core"

    async def test_ready_returns_200_after_startup(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["service"] == "core"
        assert body["checks"]["database"] == "ok"

    async def test_health_does_not_require_tenant(self, client: AsyncClient) -> None:
        # Liveness probes never carry a tenant — they must succeed without one.
        response = await client.get("/api/v1/health")
        assert response.status_code == 200

    async def test_ready_does_not_require_tenant(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/ready")
        assert response.status_code == 200
