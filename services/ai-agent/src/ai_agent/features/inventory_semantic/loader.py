"""Product catalog loader for ``inventory reindex`` (SKY-70) - feature layer.

Fetches the products a tenant may search, page by page, from the core
monolith's existing catalog endpoint. Only the four searchable fields pass
through (id, sku, name, category, unit) - reorder points are NOT embedded
and money/PII never leave the trust boundary (inventory AI spec §5.5), the
same whitelist rule the RAG module loader enforces.

Uses the ingest service token (AI_INGEST_TOKEN) as bearer: a reindex is a
machine-to-machine operation, not one user's session.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import structlog

from ai_agent.core.exceptions import AiUnavailableError
from ai_agent.features.inventory_semantic.snapshot import ProductSnapshot

logger = structlog.get_logger("ai_agent.inventory_reindex")

_CATALOG_PATH = "/api/v1/inventory/products"
_PAGE_SIZE = 100
_MAX_PAGES = 40  # 4000 products ceiling guard; reindexes scale by page count.

# Searchable fields only - keep in step with ProductSnapshot.
_SNAPSHOT_FIELDS: tuple[str, ...] = ("sku", "name", "category", "unit")


class _Page:
    """One validated envelope page: raw items + the pagination fact."""

    def __init__(self, items: list[dict[str, Any]], total_pages: int) -> None:
        self.items = items
        self.total_pages = total_pages


class ProductSnapshotLoader:
    """Paginate core's product catalog into snapshot rows for one tenant."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        tenant_slug: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not base_url.strip().lower().startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._tenant_slug = tenant_slug
        self._timeout_seconds = max(timeout_seconds, 1.0)

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=self._timeout_seconds)

    async def load_all(self) -> list[ProductSnapshot]:
        """Fetch every product row; transport failures are typed 503s."""
        products: list[ProductSnapshot] = []
        for page in range(1, _MAX_PAGES + 1):
            page_data = await self._fetch_page(page)
            products.extend(_to_snapshot(row) for row in page_data.items)
            if page >= page_data.total_pages:
                return products
        logger.warning(
            "inventory_reindex.page_ceiling_hit",
            max_pages=_MAX_PAGES,
            tenant_slug=self._tenant_slug,
        )
        return products

    async def _fetch_page(self, page: int) -> _Page:
        headers = {
            "Authorization": f"Bearer {self._bearer_token}",
            "X-Tenant-Slug": self._tenant_slug,
        }
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}{_CATALOG_PATH}",
                    params={"page": page, "page_size": _PAGE_SIZE},
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "inventory_reindex.http_error",
                status_code=exc.response.status_code,
            )
            raise AiUnavailableError("Core service could not serve the product catalog") from exc
        except httpx.HTTPError as exc:
            logger.warning("inventory_reindex.transport_error")
            raise AiUnavailableError("Core service is unreachable for the product catalog") from exc

        try:
            body = response.json()
            data = body["data"]
            meta = body.get("meta", {})
            if not isinstance(data, list):
                raise TypeError("data must be a list")
            total_pages = int(meta.get("total_pages", 1))
            if total_pages < 1:
                raise TypeError("total_pages must be >= 1")
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("inventory_reindex.invalid_envelope")
            raise AiUnavailableError("Core service returned an unusable envelope") from exc
        return _Page(items=data, total_pages=total_pages)


def _to_snapshot(row: dict[str, Any]) -> ProductSnapshot:
    """Extract the searchable fields; malformed rows fail the reindex loudly."""
    return ProductSnapshot(
        product_id=uuid.UUID(str(row["id"])),
        sku=_as_text(row.get("sku")) or "",
        name=_as_text(row.get("name")) or "",
        category=_as_text(row.get("category")),
        unit=_as_text(row.get("unit")),
    )


def _as_text(value: object) -> str | None:
    """Coerce a catalog field to str, keeping None/missing as None."""
    if value is None:
        return None
    return str(value)
