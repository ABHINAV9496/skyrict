"""Unit tests for the L4 core gateway (httpx MockTransport).

Strict gateway: transport failures and non-200 responses raise
AiUnavailableError (no graceful degradation — the caller already passed
erp.hr.ai.planning at the core proxy edge).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.l4.gateway import HttpL4CoreGateway

Handler = Callable[[httpx.Request], httpx.Response]


def _make_gateway(handler: Handler) -> tuple[HttpL4CoreGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    gateway = HttpL4CoreGateway(
        bearer_token="test-token-abc",
        tenant_slug="test-tenant",
    )
    gateway._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5,
        transport=httpx.MockTransport(transport_handler),
    )
    return gateway, seen


def _envelope(data: object) -> dict[str, Any]:
    return {"success": True, "data": data, "message": "ok"}


_PAYROLL_BASE_DATA = {
    "tenant_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "as_of": "2026-01-01",
    "currency": "USD",
    "headcount": 2,
    "monthly_salary_total": "10250.00",
    "monthly_benefit_cost_total": "3000.00",
    "employees": [
        {
            "employee_id": "11111111-1111-4111-8111-111111111111",
            "employee_number": "EMP-0001",
            "first_name": "Alice",
            "last_name": "Smith",
            "department_id": None,
            "department_name": None,
            "job_title": "Engineer",
            "employment_status": "active",
            "hire_date": "2025-01-01",
            "monthly_salary": "5000.00",
            "currency": "USD",
            "monthly_benefit_cost": "1500.00",
        },
        {
            "employee_id": "22222222-2222-4222-8222-222222222222",
            "employee_number": "EMP-0002",
            "first_name": "Bob",
            "last_name": "Jones",
            "department_id": None,
            "department_name": None,
            "job_title": "Designer",
            "employment_status": "active",
            "hire_date": "2025-06-01",
            "monthly_salary": "5250.00",
            "currency": "USD",
            "monthly_benefit_cost": "1500.00",
        },
    ],
}


class TestForwarding:
    async def test_forwards_caller_token_and_tenant_slug(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_PAYROLL_BASE_DATA))

        gateway, seen = _make_gateway(handler)
        await gateway.get_payroll_base(as_of="2026-01-01")

        assert seen[0].headers["Authorization"] == "Bearer test-token-abc"
        assert seen[0].headers["X-Tenant-Slug"] == "test-tenant"
        assert seen[0].url.path == "/api/v1/ai/hr/l4/payroll-base"
        assert "as_of=2026-01-01" in seen[0].url.query.decode()


class TestParsing:
    async def test_returns_unwrapped_data_dict(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_PAYROLL_BASE_DATA))

        gateway, _ = _make_gateway(handler)
        result = await gateway.get_payroll_base(as_of="2026-01-01")

        assert isinstance(result, dict)
        assert result["currency"] == "USD"
        assert result["headcount"] == 2
        assert isinstance(result["employees"], list)
        assert len(result["employees"]) == 2

    async def test_passes_empty_as_of_when_not_given(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_PAYROLL_BASE_DATA))

        gateway, seen = _make_gateway(handler)
        await gateway.get_payroll_base(as_of="")

        assert b"as_of" not in seen[0].url.query


class TestErrors:
    async def test_transport_error_raises_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError, match="temporarily unavailable"):
            await gateway.get_payroll_base(as_of="2026-01-01")

    async def test_non_200_raises_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "forbidden"})

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError, match="status 403"):
            await gateway.get_payroll_base(as_of="2026-01-01")

    async def test_bad_json_raises_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError, match="unusable response"):
            await gateway.get_payroll_base(as_of="2026-01-01")

    async def test_missing_data_key_raises_ai_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"success": True, "message": "ok"})

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError, match="invalid payload"):
            await gateway.get_payroll_base(as_of="2026-01-01")
