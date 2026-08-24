"""Unit tests for the health/readiness endpoints."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from ai_agent.api import readiness
from ai_agent.core.constants import SERVICE_NAME
from ai_agent.main import create_app


def _client() -> TestClient:
    """Build a TestClient without triggering lifespan startup verification."""
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_health_reports_service_name() -> None:
    client = _client()
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body == {"status": "healthy", "service": SERVICE_NAME}


def test_ready_returns_503_while_gate_is_closed() -> None:
    readiness.reset()
    assert readiness.is_ready() is False

    client = _client()
    try:
        response = client.get("/api/v1/ready")
    finally:
        readiness.mark_stopping()

    assert response.status_code == 503
    body: dict[str, Any] = response.json()
    assert body["status"] == "not_ready"
    assert body["service"] == SERVICE_NAME


def test_ready_returns_503_when_live_probe_fails(monkeypatch) -> None:
    async def _fail() -> None:
        raise ConnectionError("database down")

    monkeypatch.setattr(readiness, "check_database", _fail)
    monkeypatch.setattr(
        readiness,
        "check_redis",
        lambda: _noop_ok(),
    )
    readiness.mark_ready()
    client = _client()
    try:
        response = client.get("/api/v1/ready")
    finally:
        readiness.mark_stopping()

    assert response.status_code == 503
    body: dict[str, Any] = response.json()
    assert body["checks"]["database"] == "failed"
    assert body["checks"]["redis"] == "ok"


async def _noop_ok() -> None:
    return None


def test_ready_returns_200_when_probes_pass(monkeypatch) -> None:
    monkeypatch.setattr(readiness, "check_database", _noop_ok)
    monkeypatch.setattr(readiness, "check_redis", _noop_ok)
    readiness.mark_ready()
    client = _client()
    try:
        response = client.get("/api/v1/ready")
    finally:
        readiness.mark_stopping()

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": "ok", "redis": "ok"}
