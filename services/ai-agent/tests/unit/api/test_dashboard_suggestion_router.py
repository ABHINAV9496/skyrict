"""Unit tests for the /ai/dashboards/suggest wire endpoints (BUG-AI-002).

The router is exercised through a minimal TestClient app (no lifespan/db),
with auth stubbed to a fixed caller, the feature flag toggled per test, and
the telemetry gateway replaced by a scripted fake. Covers: the 501 gate when
the flag is off, and the flag-on wire flow including response mapping.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, call

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_agent.api.deps import get_current_user
from ai_agent.api.v1.routers import dashboard_suggestion as dashboard_router
from ai_agent.core.config import settings
from ai_agent.features.dashboard_suggestion.gateway import EventSummary, WidgetTelemetry

if TYPE_CHECKING:
    import pytest

_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
_CALLER = {
    "user_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "tenant_id": _TENANT_ID,
    "token_payload": {"sub": "11111111-1111-4111-8111-111111111111"},
}

_SUMMARY = EventSummary(
    items=[
        WidgetTelemetry(widget_id="ai_digest", total_events=60, distinct_events=2),
        WidgetTelemetry(widget_id="erp_overview", total_events=2, distinct_events=1),
    ],
    suggestion_ready=True,
)


class _FakeGateway:
    """Scripted stand-in for the telemetry gateway."""

    def __init__(self, summary: EventSummary) -> None:
        self._summary = summary

    async def get_event_summary(self) -> EventSummary:
        return self._summary


class _NullLlmRouter:
    has_providers = False


def _app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    gateway: Any,
) -> TestClient:
    monkeypatch.setattr(settings, "DASHBOARD_SUGGEST_ENABLED", enabled)
    app = FastAPI()
    app.include_router(dashboard_router.router, prefix="/api/v1")
    app.state.llm_router = _NullLlmRouter()
    app.dependency_overrides[get_current_user] = lambda: _CALLER

    def _fake_gateway(request: object) -> Any:
        return gateway

    monkeypatch.setattr(dashboard_router, "get_dashboard_gateway", _fake_gateway)
    return TestClient(app)


class TestSuggestLayout:
    def test_501_when_flag_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch, enabled=False, gateway=_FakeGateway(_SUMMARY))

        response = client.post(
            "/api/v1/ai/dashboards/suggest",
            json={"current_layout": []},
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 501
        assert "not enabled" in response.json()["detail"]

    def test_flag_off_never_enforces_rate_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        enforce = AsyncMock()
        monkeypatch.setattr(dashboard_router.limiter, "enforce", enforce)
        client = _app(monkeypatch, enabled=False, gateway=_FakeGateway(_SUMMARY))

        client.post(
            "/api/v1/ai/dashboards/suggest",
            json={"current_layout": []},
            headers={"authorization": "Bearer t"},
        )

        enforce.assert_not_called()

    def test_flag_on_enforces_per_user_and_tenant_limits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enforce = AsyncMock()
        monkeypatch.setattr(dashboard_router.limiter, "enforce", enforce)
        gateway = _FakeGateway(EventSummary(items=[], suggestion_ready=False))
        client = _app(monkeypatch, enabled=True, gateway=gateway)

        client.post(
            "/api/v1/ai/dashboards/suggest",
            json={"current_layout": []},
            headers={"authorization": "Bearer t"},
        )

        assert enforce.await_args_list == [
            call(
                key=f"ai:dashboard_suggest:{_CALLER['user_id']}",
                limit=settings.RATE_LIMIT_DASHBOARD_SUGGEST_PER_MIN,
                window_seconds=60,
            ),
            call(
                key=f"ai:tenant_total:{_TENANT_ID}",
                limit=settings.RATE_LIMIT_TENANT_PER_MIN,
                window_seconds=60,
            ),
        ]

    def test_insufficient_data_maps_to_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gateway = _FakeGateway(EventSummary(items=[], suggestion_ready=False))
        client = _app(monkeypatch, enabled=True, gateway=gateway)

        payload = {
            "current_layout": [
                {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
            ]
        }
        response = client.post(
            "/api/v1/ai/dashboards/suggest",
            json=payload,
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "insufficient_data"
        assert len(data["suggested_layout"]) == 1
        assert data["suggested_layout"][0]["id"] == "ai_digest"
        assert data["confidence"] == 0.0

    def test_no_provider_fallback_when_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _app(monkeypatch, enabled=True, gateway=_FakeGateway(_SUMMARY))

        payload = {
            "current_layout": [
                {"id": "ai_digest", "order": 0, "cols": 4, "visible": True},
            ]
        }
        response = client.post(
            "/api/v1/ai/dashboards/suggest",
            json=payload,
            headers={"authorization": "Bearer t"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "fallback"
        assert data["suggested_layout"][0]["id"] == "ai_digest"
        assert data["confidence"] == 0.0
