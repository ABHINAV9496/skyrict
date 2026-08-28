"""Unit tests for RAG source loaders (SKY-58) — docs FS and module API."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.rag.ingest.loader import (
    MODULE_FIELD_WHITELISTS,
    DocsLoader,
    ModuleLoader,
    SourceDocument,
)


class TestDocsLoader:
    def test_loads_markdown_files_sorted_and_skips_empty(self, tmp_path) -> None:
        (tmp_path / "b.md").write_text("# B file\ncontent", encoding="utf-8")
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "a.md").write_text("# A file\ncontent", encoding="utf-8")
        (tmp_path / "empty.md").write_text("   \n", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("not markdown", encoding="utf-8")

        docs = DocsLoader(root=tmp_path).load()

        assert [d.source_ref for d in docs] == ["b.md", "sub/a.md"]
        assert all(isinstance(d, SourceDocument) for d in docs)
        assert docs[0].module == "docs"
        assert "# B file" in docs[0].text

    def test_non_directory_root_rejected(self, tmp_path) -> None:
        file = tmp_path / "file.md"
        file.write_text("# x", encoding="utf-8")
        with pytest.raises(ValueError, match="not a directory"):
            DocsLoader(root=file).load()


def _make_loader(
    handler: Any,
    *,
    tenant_slug: str = "acme-corp",
) -> tuple[ModuleLoader, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    loader = ModuleLoader(
        base_url="https://core.internal",
        bearer_token="ops-token-123",
        tenant_slug=tenant_slug,
        timeout_seconds=5,
    )
    loader._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5,
        transport=httpx.MockTransport(transport_handler),
    )
    return loader, seen


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


class TestModuleLoader:
    def test_whitelist_never_contains_money_or_pii_fields(self) -> None:
        for fields in MODULE_FIELD_WHITELISTS.values():
            for field in fields:
                assert field not in {
                    "cost_price",
                    "sell_price",
                    "reorder_point",
                    "qty",
                    "customer_name",
                    "supplier_name",
                    "user_id",
                }, f"whitelisted field {field} must not carry money/PII"

    async def test_forwards_token_and_tenant_slug_headers(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([_PRODUCT]))

        loader, seen = _make_loader(handler)
        docs = await loader.load("products")

        assert seen[0].headers["Authorization"] == "Bearer ops-token-123"
        assert seen[0].headers["X-Tenant-Slug"] == "acme-corp"
        assert seen[0].url.path == "/api/v1/inventory/products"
        assert len(docs) == 1

    async def test_renders_only_whitelisted_fields(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([_PRODUCT]))

        loader, _ = _make_loader(handler)
        docs = await loader.load("products")

        text = docs[0].text
        assert "## products:00000000-0000-0000-0000-000000000001" in text
        assert "- name: Laptop Charger 65W" in text
        assert "- sku: LAPTOP-CHG-001" in text
        # Money and other fields are NOT rendered even when present.
        assert "reorder_point" not in text
        assert docs[0].source_ref == "products/00000000-0000-0000-0000-000000000001"

    async def test_paginates_until_last_page(self) -> None:
        pages_requested: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params["page"]
            pages_requested.append(page)
            if page == "1":
                return httpx.Response(200, json=_envelope([_PRODUCT], page=1, total_pages=2))
            return httpx.Response(
                200,
                json=_envelope(
                    [dict(_PRODUCT, id="00000000-0000-0000-0000-000000000002", sku="CABLE-USB-01")],
                    page=2,
                    total_pages=2,
                ),
            )

        loader, _ = _make_loader(handler)
        docs = await loader.load("products")

        assert pages_requested == ["1", "2"]
        assert len(docs) == 2

    async def test_blank_rows_are_skipped(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([{"id": "123", "name": "  ", "sku": ""}]))

        loader, _ = _make_loader(handler)
        docs = await loader.load("products")
        assert docs == []

    async def test_rows_without_id_are_skipped(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_envelope([{"name": "No Id", "sku": "X"}]))

        loader, _ = _make_loader(handler)
        docs = await loader.load("products")
        assert docs == []

    async def test_unknown_module_rejected(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no network for unknown module")

        loader, _ = _make_loader(handler)
        with pytest.raises(ValueError, match="no configured endpoint"):
            await loader.load("payroll")

    async def test_core_outage_maps_to_typed_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        loader, _ = _make_loader(handler)
        with pytest.raises(AiUnavailableError):
            await loader.load("products")

    async def test_unusable_envelope_maps_to_typed_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not the api</html>")

        loader, _ = _make_loader(handler)
        with pytest.raises(AiUnavailableError):
            await loader.load("products")

    async def test_http_error_status_maps_to_typed_503(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "bad token"})

        loader, _ = _make_loader(handler)
        with pytest.raises(AiUnavailableError):
            await loader.load("products")
