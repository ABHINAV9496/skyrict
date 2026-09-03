"""Unit tests for the HTTP Finance gateway adapter (httpx MockTransport).

Every read must forward the caller's JWT + tenant slug unchanged so core
enforces ``erp.finance.read`` and tenant isolation. Money fields stay Decimal.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.finance.gateway import HttpFinanceGateway

ACCOUNT_ID = "00000000-0000-0000-0000-000000000001"
INVOICE_ID = "00000000-0000-0000-0000-000000000002"


def _make_gateway(handler: Any) -> tuple[HttpFinanceGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    gateway = HttpFinanceGateway(
        base_url="https://core.internal",
        bearer_token="user-token-123",
        tenant_slug="acme-corp",
    )
    gateway._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5, transport=httpx.MockTransport(transport_handler)
    )
    return gateway, seen


def _envelope(data: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    return {"success": True, "data": data}


def _list_envelope(
    data: list[dict[str, Any]], *, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "meta": {"total": len(data), "page": (offset // limit) + 1, "page_size": limit},
    }


_ACCOUNT = {
    "id": ACCOUNT_ID,
    "tenant_id": "00000000-0000-0000-0000-000000000099",
    "code": "4100",
    "name": "Sales Revenue",
    "account_type": "revenue",
    "is_active": True,
    "created_at": None,
    "updated_at": None,
}

_INVOICE = {
    "id": INVOICE_ID,
    "tenant_id": "00000000-0000-0000-0000-000000000099",
    "invoice_number": "INV-0001",
    "customer_id": "00000000-0000-0000-0000-000000000005",
    "customer_name": "Acme Foods",
    "invoice_date": "2026-08-15",
    "due_date": "2026-09-14",
    "status": "issued",
    "total": "4500.0000",
    "source": "manual",
    "source_ref": None,
    "source_order_number": None,
    "lines": [],
    "issued_at": "2026-08-15T09:00:00+00:00",
    "approved_at": None,
    "voided_at": None,
    "created_at": None,
    "updated_at": None,
}

_PNL = {
    "from_date": "2026-08-01",
    "to_date": "2026-08-31",
    "revenue": [],
    "expenses": [],
    "total_revenue": "120000.0000",
    "total_expenses": "80000.0000",
    "net_income": "40000.0000",
}

_AR = {
    "as_of": "2026-08-31",
    "total_ar": "9000.0000",
    "buckets": [
        {"bucket": "current", "count": 5, "amount": "4000.0000", "share": "0.4444"},
        {"bucket": ">90", "count": 2, "amount": "5000.0000", "share": "0.5556"},
    ],
}


class TestForwarding:
    async def test_forwards_caller_token_and_tenant_slug(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_PNL))

        gateway, seen = _make_gateway(handler)
        await gateway.get_pnl()

        assert seen[0].headers["Authorization"] == "Bearer user-token-123"
        assert seen[0].headers["X-Tenant-Slug"] == "acme-corp"
        assert seen[0].url.path == "/api/v1/finance/reports/profit-and-loss"


class TestListAccounts:
    async def test_parses_account_rows(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/finance/accounts"
            return httpx.Response(200, json=_envelope([_ACCOUNT]))

        gateway, _ = _make_gateway(handler)
        accounts = await gateway.list_accounts()

        assert len(accounts) == 1
        account = accounts[0]
        assert account.id == uuid.UUID(ACCOUNT_ID)
        assert account.code == "4100"
        assert account.name == "Sales Revenue"
        assert account.account_type == "revenue"

    async def test_non_list_payload_degrades_to_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope({"unexpected": True}))

        gateway, _ = _make_gateway(handler)
        assert await gateway.list_accounts() == []


class TestListInvoices:
    async def test_parses_invoice_and_keeps_decimal_money(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["offset"] == "0"
            assert request.url.params["limit"] == "100"
            return httpx.Response(200, json=_list_envelope([_INVOICE], limit=100))

        gateway, _ = _make_gateway(handler)
        invoices = await gateway.list_invoices()

        assert len(invoices) == 1
        invoice = invoices[0]
        assert invoice.invoice_number == "INV-0001"
        assert invoice.customer_name == "Acme Foods"
        assert invoice.status == "issued"
        assert invoice.total == Decimal("4500.0000")
        assert invoice.invoice_date == date(2026, 8, 15)
        assert invoice.due_date == date(2026, 9, 14)
        assert invoice.issued_at == datetime(2026, 8, 15, 9, 0, tzinfo=_utc())

    async def test_stops_when_page_is_not_full(self) -> None:
        calls: list[int] = []
        full_page = [_INVOICE] * 100  # a full page of 100 -> keep reading

        async def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params["offset"])
            calls.append(offset)
            if offset == 0:
                return httpx.Response(200, json=_list_envelope(full_page, offset=0, limit=100))
            # Second page returns fewer rows than requested -> stop.
            return httpx.Response(200, json=_list_envelope([], offset=100, limit=100))

        gateway, _ = _make_gateway(handler)
        invoices = await gateway.list_invoices()

        assert len(invoices) == 100
        assert calls == [0, 100]

    async def test_unreachable_core_raises_typed_unavailable(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.list_invoices()


class TestGetPnl:
    async def test_parses_pnl_keeps_decimal_money(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_PNL))

        gateway, _ = _make_gateway(handler)
        pnl = await gateway.get_pnl()

        assert pnl is not None
        assert pnl.from_date == date(2026, 8, 1)
        assert pnl.to_date == date(2026, 8, 31)
        assert pnl.total_revenue == Decimal("120000.0000")
        assert pnl.total_expenses == Decimal("80000.0000")
        assert pnl.net_income == Decimal("40000.0000")

    async def test_forbidden_degrades_to_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        gateway, _ = _make_gateway(handler)
        assert await gateway.get_pnl() is None


class TestGetArAging:
    async def test_parses_buckets(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope(_AR))

        gateway, _ = _make_gateway(handler)
        ar = await gateway.get_ar_aging()

        assert ar is not None
        assert ar.as_of == date(2026, 8, 31)
        assert ar.total_ar == Decimal("9000.0000")
        assert len(ar.buckets) == 2
        assert ar.buckets[0].bucket == "current"
        assert ar.buckets[0].count == 5
        assert ar.buckets[0].amount == Decimal("4000.0000")

    async def test_forbidden_degrades_to_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        gateway, _ = _make_gateway(handler)
        assert await gateway.get_ar_aging() is None


def _utc() -> Any:
    import zoneinfo

    return zoneinfo.ZoneInfo("UTC")
