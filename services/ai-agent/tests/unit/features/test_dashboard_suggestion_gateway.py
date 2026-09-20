"""Unit tests for the dashboard telemetry gateway adapter (httpx MockTransport)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import (
    AiUnavailableError,
    AuthorizationError,
    NotFoundError,
)
from ai_agent.features.dashboard_suggestion.gateway import HttpDashboardGateway


def _make_gateway(handler: Any) -> tuple[HttpDashboardGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[no-any-return]

    gateway = HttpDashboardGateway(
        base_url="https://core.internal",
        bearer_token="user-token-123",
        tenant_slug="acme-corp",
    )
    gateway._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5, transport=httpx.MockTransport(transport_handler)
    )
    return gateway, seen


class TestGetEventSummary:
    async def test_forwards_caller_token_and_tenant_slug(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "widget_id": "ai_digest",
                            "total_events": 60,
                            "distinct_events": 2,
                        }
                    ],
                    "suggestion_ready": True,
                },
            )

        gateway, seen = _make_gateway(handler)
        summary = await gateway.get_event_summary()

        assert seen[0].headers["Authorization"] == "Bearer user-token-123"
        assert seen[0].headers["X-Tenant-Slug"] == "acme-corp"
        assert seen[0].url.path == "/api/v1/dashboards/me/events/summary"
        assert summary.suggestion_ready is True
        assert summary.items[0].widget_id == "ai_digest"
        assert summary.items[0].total_events == 60

    async def test_not_ready_when_threshold_not_met(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"items": [{"widget_id": "ai_digest", "total_events": 3, "distinct_events": 1}], "suggestion_ready": False},
            )

        gateway, _ = _make_gateway(handler)
        summary = await gateway.get_event_summary()

        assert summary.suggestion_ready is False
        assert summary.items[0].total_events == 3

    async def test_empty_items(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"items": [], "suggestion_ready": False})

        gateway, _ = _make_gateway(handler)
        summary = await gateway.get_event_summary()

        assert summary.items == []
        assert summary.suggestion_ready is False

    async def test_401_maps_to_authorization_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "no"})

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AuthorizationError):
            await gateway.get_event_summary()

    async def test_404_maps_to_not_found(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "no"})

        gateway, _ = _make_gateway(handler)
        with pytest.raises(NotFoundError):
            await gateway.get_event_summary()

    async def test_503_maps_to_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "boom"})

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.get_event_summary()

    async def test_bad_body_maps_to_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.get_event_summary()

    async def test_transport_failure_maps_to_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.get_event_summary()
