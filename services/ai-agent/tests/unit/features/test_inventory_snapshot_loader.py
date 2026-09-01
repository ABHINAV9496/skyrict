"""Unit tests for the product snapshot loader (SKY-70).

Paginates core's catalog through an in-memory httpx transport (no network):
envelope parsing, pagination flattening, whitelisted-field extraction, and
the typed AiUnavailableError mapping for transport/schema failures.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.inventory_semantic.loader import ProductSnapshotLoader

if TYPE_CHECKING:
    from collections.abc import Callable

BASE_URL = "http://core.test"
PAGES: dict[int, list[dict[str, object]]] = {}


def _row(pid: uuid.UUID, *, category: str | None = None) -> dict[str, object]:
    return {
        "id": str(pid),
        "sku": "CBL-100",
        "name": "Cat6 Patch Cable",
        "category": category,
        "unit": "m",
        "reorder_point": "5.00",
    }


@pytest.fixture(autouse=True)
def _reset_pages() -> None:
    PAGES.clear()


def _handler_factory() -> Callable[[httpx.Request], httpx.Response]:
    """Build an httpx handler serving the currently configured PAGES table."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        rows = PAGES.get(page, [])
        body = {"success": True, "data": rows, "meta": {"total_pages": len(PAGES)}}
        return httpx.Response(200, json=body)

    return handler


def _loader() -> ProductSnapshotLoader:
    loader = ProductSnapshotLoader(
        base_url=BASE_URL,
        bearer_token="ingest-secret",
        tenant_slug="acme",
    )
    transport = httpx.MockTransport(_handler_factory())
    loader._create_client = lambda: httpx.AsyncClient(transport=transport, timeout=1.0)
    return loader


class TestProductSnapshotLoader:
    @pytest.mark.anyio
    async def test_load_all_paginates_and_extracts_searchable_fields(self) -> None:
        p1 = uuid.uuid4()
        p2 = uuid.uuid4()
        PAGES[1] = [_row(p1, category="Networking")]
        PAGES[2] = [_row(p2)]

        products = await _loader().load_all()

        assert len(products) == 2
        assert products[0].product_id == p1
        assert products[0].sku == "CBL-100"
        assert products[0].name == "Cat6 Patch Cable"
        assert products[0].category == "Networking"
        assert products[0].unit == "m"
        assert products[1].category is None

    @pytest.mark.anyio
    async def test_single_page_stops_early(self) -> None:
        PAGES[1] = [_row(uuid.uuid4(), category="Networking")]

        products = await _loader().load_all()
        assert len(products) == 1

    @pytest.mark.anyio
    async def test_transport_failure_is_typed_503(self) -> None:
        def failing(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        loader = ProductSnapshotLoader(base_url=BASE_URL, bearer_token="x", tenant_slug="acme")
        loader._create_client = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(failing), timeout=1.0
        )

        with pytest.raises(AiUnavailableError):
            await loader.load_all()

    @pytest.mark.anyio
    async def test_unusable_envelope_is_typed_503(self) -> None:
        def bad(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=json.dumps({"success": True}).encode())

        loader = ProductSnapshotLoader(base_url=BASE_URL, bearer_token="x", tenant_slug="acme")
        loader._create_client = lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(bad), timeout=1.0
        )

        with pytest.raises(AiUnavailableError):
            await loader.load_all()
