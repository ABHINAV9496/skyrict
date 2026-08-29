"""Unit tests for the HTTP HR gateway adapter (httpx MockTransport)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.hr_copilot.gateway import HttpHrGateway

Handler = Callable[[httpx.Request], httpx.Response]


def _make_gateway(handler: Handler) -> tuple[HttpHrGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    gateway = HttpHrGateway(
        base_url="https://core.internal",
        bearer_token="user-token-123",
        tenant_slug="acme-corp",
    )
    gateway._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5, transport=httpx.MockTransport(transport_handler)
    )
    return gateway, seen


def _envelope(data: object) -> dict[str, Any]:
    return {"success": True, "data": data, "message": "ok"}


_OVERVIEW = {
    "total_headcount": 120,
    "trend": [],
    "departments": [
        {"department_name": "Engineering", "count": 40},
        {"department_name": "Sales", "count": 25},
    ],
    "tenure_bands": [{"band": "1-3", "count": 70}],
    "narrative": "Headcount grew 4% MoM.",
}

_TENURE = {
    "total_headcount": 120,
    "bands": [{"band": "1-3", "count": 70}],
    "narrative": "Tenure concentrated at 1-3 years.",
}

_POLICY = {
    "casual_days_per_year": 12,
    "sick_days_per_year": 8,
    "effective_from": "2026-01-01",
}


class TestForwarding:
    async def test_forwards_caller_token_and_tenant_slug(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_OVERVIEW))

        gateway, seen = _make_gateway(handler)
        await gateway.get_overview()

        assert seen[0].headers["Authorization"] == "Bearer user-token-123"
        assert seen[0].headers["X-Tenant-Slug"] == "acme-corp"
        assert seen[0].url.path == "/api/v1/ai/hr/overview"


class TestParsing:
    async def test_overview_parsed_into_aggregate_context(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_OVERVIEW))

        gateway, _ = _make_gateway(handler)
        ctx = await gateway.get_overview()

        assert ctx is not None
        assert ctx.total_headcount == 120
        assert ctx.departments == (("Engineering", 40), ("Sales", 25))
        assert ctx.tenure_bands == (("1-3", 70),)
        assert ctx.narrative == "Headcount grew 4% MoM."

    async def test_leave_policy_parsed(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_POLICY))

        gateway, seen = _make_gateway(handler)
        ctx = await gateway.get_leave_policy()

        assert ctx is not None
        assert ctx.casual_days_per_year == 12
        assert ctx.sick_days_per_year == 8
        assert ctx.effective_from == "2026-01-01"
        assert seen[0].url.path == "/api/v1/hr/leave/policy"


class TestDegradation:
    async def test_non_200_degrades_to_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json=_envelope(None))

        gateway, _ = _make_gateway(handler)
        assert await gateway.get_tenure() is None

    async def test_transport_error_maps_to_typed_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.get_tenure()
