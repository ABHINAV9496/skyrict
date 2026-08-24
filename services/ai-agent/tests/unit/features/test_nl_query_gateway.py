"""Unit tests for the HTTP inventory gateway adapter (httpx MockTransport)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.nl_query.gateway import HttpInventoryGateway


def _make_gateway(
    handler: Any,
) -> tuple[HttpInventoryGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    gateway = HttpInventoryGateway(
        base_url="https://core.internal",
        bearer_token="user-token-123",
        tenant_slug="acme-corp",
    )
    # Swap the client factory for one bound to the mock transport (mirrors
    # the production per-call client construction).
    gateway._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5, transport=httpx.MockTransport(transport_handler)
    )
    return gateway, seen


def _envelope(data: list[dict[str, Any]], page: int = 1, total_pages: int = 1) -> dict[str, Any]:
    return {
        "success": True,
        "data": data,
        "meta": {"total": len(data), "page": page, "page_size": 100, "total_pages": total_pages},
    }


_PRODUCT = {
    "id": "00000000-0000-0000-0000-000000000001",
    "sku": "LAPTOP-CHG-001",
    "name": "Laptop Charger 65W",
    "reorder_point": "10.0000",
}


class TestForwarding:
    async def test_forwards_caller_token_and_tenant_slug(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([_PRODUCT]))

        gateway, seen = _make_gateway(handler)
        await gateway.list_products()

        assert seen[0].headers["Authorization"] == "Bearer user-token-123"
        assert seen[0].headers["X-Tenant-Slug"] == "acme-corp"
        assert seen[0].url.path == "/api/v1/inventory/products"


class TestParsing:
    async def test_decimal_strings_become_decimals(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([_PRODUCT]))

        gateway, _ = _make_gateway(handler)
        products = await gateway.list_products()

        assert products[0].reorder_point == Decimal("10.0000")

    async def test_multi_page_catalogs_fetched_until_last_page(self) -> None:
        pages_requested: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params["page"]
            pages_requested.append(page)
            if page == "1":
                return httpx.Response(
                    200,
                    json=_envelope([_PRODUCT], page=1, total_pages=2),
                )
            return httpx.Response(
                200,
                json=_envelope([dict(_PRODUCT, sku="SECOND")], page=2, total_pages=2),
            )

        gateway, _ = _make_gateway(handler)
        products = await gateway.list_products()

        assert pages_requested == ["1", "2"]
        assert [p.sku for p in products] == ["LAPTOP-CHG-001", "SECOND"]

    async def test_core_outage_maps_to_typed_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.list_products()

    async def test_unusable_envelope_maps_to_typed_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not the api</html>")

        gateway, _ = _make_gateway(handler)
        with pytest.raises(AiUnavailableError):
            await gateway.list_products()


class TestMovementFilters:
    async def test_movement_params_forwarded_lowercased(self) -> None:
        movement = {
            "id": "20000000-0000-0000-0000-000000000001",
            "product_id": "00000000-0000-0000-0000-000000000001",
            "warehouse_id": "10000000-0000-0000-0000-000000000001",
            "movement_type": "receipt",
            "qty": "25.0000",
            "ref_type": "purchase_order",
            "ref_id": None,
            "created_at": "2026-08-20T10:00:00Z",
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([movement]))

        gateway, _ = _make_gateway(handler)
        rows = await gateway.list_movements(movement_type="receipt")

        assert rows[0].qty == Decimal("25.0000")
        assert rows[0].created_at.year == 2026
