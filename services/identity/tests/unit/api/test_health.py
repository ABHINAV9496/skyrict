"""Unit tests for identity/api/v1/health.py — /health and the hybrid /ready probe.

Uses a dedicated FastAPI app with only the health router (no middleware, no
lifespan) so the handler logic is tested in isolation. Dependency probes are
stubbed; the readiness gate is reset per test because it is module-global.

Verifies:
  - /health always reports 200 healthy (liveness — no dependency checks)
  - /ready returns 503 until the gate opens (startup verification)
  - once the gate opens, /ready runs live probes and returns 200 only when
    database AND redis succeed; a failed probe returns 503 with a checks map
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI

from identity.api import readiness
from identity.api.v1.health import router as health_router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture(autouse=True)
def _reset_gate():
    """The gate is module-global — reset it so tests are order-independent."""
    readiness.reset()


@pytest.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Throwaway app mounting only the health router (no lifespan, no middleware)."""
    app = FastAPI()
    app.include_router(health_router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _ok_probe() -> None:
    return None


class TestHealthCheck:
    """Liveness — process up, no dependency checks."""

    async def test_health_returns_200(self, http_client: httpx.AsyncClient):
        response = await http_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "service": "identity"}


class TestReadinessCheck:
    """Readiness — gated on startup verification, then live probes."""

    async def test_ready_returns_503_before_startup_verification(
        self, http_client: httpx.AsyncClient
    ):
        response = await http_client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "service": "identity"}

    async def test_ready_returns_200_when_gate_open_and_probes_pass(
        self,
        http_client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(readiness, "check_database", _ok_probe)
        monkeypatch.setattr(readiness, "check_redis", _ok_probe)
        readiness.mark_ready()

        response = await http_client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "service": "identity",
            "checks": {"database": "ok", "redis": "ok"},
        }

    async def test_ready_returns_503_when_database_probe_fails(
        self,
        http_client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def _boom() -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(readiness, "check_database", _boom)
        monkeypatch.setattr(readiness, "check_redis", _ok_probe)
        readiness.mark_ready()

        response = await http_client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "service": "identity",
            "checks": {"database": "failed", "redis": "ok"},
        }

    async def test_ready_returns_503_when_redis_probe_fails(
        self,
        http_client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        async def _boom() -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(readiness, "check_database", _ok_probe)
        monkeypatch.setattr(readiness, "check_redis", _boom)
        readiness.mark_ready()

        response = await http_client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "service": "identity",
            "checks": {"database": "ok", "redis": "failed"},
        }

    async def test_ready_skips_probes_while_gate_is_closed(
        self,
        http_client: httpx.AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Probes must not run (or be trusted) before startup verification."""
        calls: list[str] = []

        async def _tracking_database() -> None:
            calls.append("database")

        async def _tracking_redis() -> None:
            calls.append("redis")

        monkeypatch.setattr(readiness, "check_database", _tracking_database)
        monkeypatch.setattr(readiness, "check_redis", _tracking_redis)

        response = await http_client.get("/ready")
        assert response.status_code == 503
        assert calls == []
