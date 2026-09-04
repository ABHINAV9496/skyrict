"""Inventory gateway - read-only access to the core monolith's data.

The AI agent owns NO inventory tables: every answer is computed from core's
existing HTTP API (spec §1.4 "AI is a proxy, not a bypass"). The
:class:`InventoryGatewayPort` protocol is what engines depend on; tests fake
it, production binds :class:`HttpInventoryGateway`.

Adapter notes (verified against core's router):
- base path ``/api/v1/inventory``; responses use the shared envelope
  ``{"success": ..., "data": [...], "meta": {...}}``;
- decimals arrive as strings and money as ``[amount, currency]`` tuples -
  converted to Decimal HERE so engines never see wire formats;
- movement types are lowercase enums (``receipt``, ``issue``, ...);
- no server-side name search or date filters exist, so catalogs are fetched
  in full (paginated, page-capped) and date filtering happens in the engine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

import httpx
import structlog

from ai_agent.core.exceptions import AiUnavailableError

logger = structlog.get_logger("ai_agent.inventory_gateway")

# Catalog fetches page through core with this guard so a pathological tenant
# cannot make one NL query loop forever. 20 pages x 100 rows = 2000 entities.
_MAX_CATALOG_PAGES = 20
_CATALOG_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ProductRef:
    """The product fields NL answers need (reorder point included)."""

    id: uuid.UUID
    sku: str
    name: str
    reorder_point: Decimal
    # Unit cost with its currency. Money is a Decimal(19,4) semantics region;
    # never sent to an LLM provider without the caller's ``erp.inventory.read``
    # permission (core returns it to any such holder - the gateway forwards the
    # caller's scoped identity, never a privileged one).
    cost_price: Decimal | None = None
    cost_currency: str | None = None
    # Semantic-search snapshot fields (SKY-70); None when core omits them.
    category: str | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class WarehouseRef:
    id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class StockLevelRow:
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    qty_on_hand: Decimal
    qty_reserved: Decimal


@dataclass(frozen=True, slots=True)
class MovementRow:
    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    movement_type: str  # lowercase enum value from core
    qty: Decimal  # signed
    created_at: datetime
    # Core echoes the originating document reference (purchase order id etc.);
    # None when the movement has no reference. Used by duplicate-ref rules.
    ref_id: str | None = None


MovementType = Literal["receipt", "issue", "transfer", "adjustment", "reservation", "release"]


@dataclass(frozen=True, slots=True)
class _ListPage:
    """One validated envelope page: raw items plus the pagination fact."""

    items: list[dict[str, object]]
    total_pages: int


class InventoryGatewayPort(Protocol):
    """Read-only inventory queries, scoped by the forwarded caller's identity."""

    async def list_products(self) -> list[ProductRef]: ...
    async def list_warehouses(self) -> list[WarehouseRef]: ...
    async def get_stock_levels(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[StockLevelRow]: ...
    async def list_movements(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: MovementType | None = None,
    ) -> list[MovementRow]: ...


class HttpInventoryGateway:
    """One request's gateway: forwards the user's JWT + tenant slug to core."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        tenant_slug: str,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._tenant_slug = tenant_slug

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._bearer_token}",
            # Core resolves tenants via subdomain in prod, X-Tenant-Slug in
            # dev/test; forwarding the slug keeps behavior identical either way.
            "X-Tenant-Slug": self._tenant_slug,
        }

    async def list_products(self) -> list[ProductRef]:
        items: list[ProductRef] = []
        for page in range(1, _MAX_CATALOG_PAGES + 1):
            items_page = await self._get_list("/products", page=page)
            items.extend(_parse_product(item) for item in items_page.items)
            if page >= items_page.total_pages:
                break
        return items

    async def list_warehouses(self) -> list[WarehouseRef]:
        items: list[WarehouseRef] = []
        for page in range(1, _MAX_CATALOG_PAGES + 1):
            items_page = await self._get_list("/warehouses", page=page)
            items.extend(_parse_warehouse(item) for item in items_page.items)
            if page >= items_page.total_pages:
                break
        return items

    async def get_stock_levels(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> list[StockLevelRow]:
        params: dict[str, str] = {}
        if product_id is not None:
            params["product_id"] = str(product_id)
        if warehouse_id is not None:
            params["warehouse_id"] = str(warehouse_id)
        items: list[StockLevelRow] = []
        for page in range(1, _MAX_CATALOG_PAGES + 1):
            items_page = await self._get_list("/stock", page=page, extra=params)
            items.extend(_parse_stock_level(item) for item in items_page.items)
            if page >= items_page.total_pages:
                break
        return items

    async def list_movements(
        self,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: MovementType | None = None,
    ) -> list[MovementRow]:
        params: dict[str, str] = {}
        if product_id is not None:
            params["product_id"] = str(product_id)
        if warehouse_id is not None:
            params["warehouse_id"] = str(warehouse_id)
        if movement_type is not None:
            params["movement_type"] = movement_type
        items: list[MovementRow] = []
        for page in range(1, _MAX_CATALOG_PAGES + 1):
            items_page = await self._get_list("/stock/movements", page=page, extra=params)
            items.extend(_parse_movement(item) for item in items_page.items)
            if page >= items_page.total_pages:
                break
        return items

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=10.0)

    async def _get_list(
        self, path: str, *, page: int, extra: dict[str, str] | None = None
    ) -> _ListPage:
        """GET one envelope page; any failure is a typed 503 for the caller."""
        params: dict[str, str] = {"page": str(page), "page_size": str(_CATALOG_PAGE_SIZE)}
        if extra:
            params.update(extra)
        try:
            async with self._create_client() as client:
                response = await client.get(
                    f"{self._base_url}/api/v1/inventory{path}",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("inventory_gateway_unreachable", path=path)
            raise AiUnavailableError("Inventory service is temporarily unavailable") from exc
        # Parse OUTSIDE the transport try-block: a 200 with an unusable body
        # is a different failure mode than "could not reach core".
        try:
            payload = response.json()
        except ValueError as exc:  # includes json.JSONDecodeError
            logger.warning("inventory_gateway_bad_body", path=path)
            raise AiUnavailableError("Inventory service returned an unusable response") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise AiUnavailableError("Inventory service returned an unusable response")
        meta = payload.get("meta")
        total_pages = meta.get("total_pages") if isinstance(meta, dict) else None
        if not isinstance(total_pages, int):
            raise AiUnavailableError("Inventory service returned an unusable response")
        return _ListPage(items=payload["data"], total_pages=total_pages)


def _parse_product(item: dict[str, object]) -> ProductRef:
    # Core serializes money as [amount-string, currency] tuples.
    raw_cost = item.get("cost_price")
    cost_price = None
    cost_currency = None
    if isinstance(raw_cost, list | tuple) and raw_cost:
        cost_price = Decimal(str(raw_cost[0]))
        if len(raw_cost) > 1 and raw_cost[1] is not None:
            cost_currency = str(raw_cost[1])
    category = item.get("category")
    unit = item.get("unit")
    return ProductRef(
        id=uuid.UUID(str(item["id"])),
        sku=str(item["sku"]),
        name=str(item["name"]),
        reorder_point=Decimal(str(item["reorder_point"])),
        cost_price=cost_price,
        cost_currency=cost_currency,
        category=None if category is None else str(category),
        unit=None if unit is None else str(unit),
    )


def _parse_warehouse(item: dict[str, object]) -> WarehouseRef:
    return WarehouseRef(id=uuid.UUID(str(item["id"])), name=str(item["name"]))


def _parse_stock_level(item: dict[str, object]) -> StockLevelRow:
    return StockLevelRow(
        product_id=uuid.UUID(str(item["product_id"])),
        warehouse_id=uuid.UUID(str(item["warehouse_id"])),
        qty_on_hand=Decimal(str(item["qty_on_hand"])),
        qty_reserved=Decimal(str(item["qty_reserved"])),
    )


def _parse_movement(item: dict[str, object]) -> MovementRow:
    created_raw = str(item["created_at"])
    # Core serializes timestamps as ISO-8601; tolerate a trailing Z.
    created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
    ref_id = item.get("ref_id")
    return MovementRow(
        id=uuid.UUID(str(item["id"])),
        product_id=uuid.UUID(str(item["product_id"])),
        warehouse_id=uuid.UUID(str(item["warehouse_id"])),
        movement_type=str(item["movement_type"]),
        qty=Decimal(str(item["qty"])),
        created_at=created_at,
        ref_id=None if ref_id is None else str(ref_id),
    )
