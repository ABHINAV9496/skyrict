"""Inventory HTTP router — thin marshalling, business rules live in the service.

Endpoints follow docs/modules/inventory-warehouse.md §8. Every route requires a
valid access JWT + tenant context (via shared deps) and a module-level
permission dependency resolved from DB grants at request time. Responses are
wrapped in ``ResponseEnvelope``; lists use offset/limit with ``PaginationMeta``.

Permissions (spec §7.3 / §8): read endpoints need ``erp.inventory.read``;
product/warehouse creation and transfers need ``erp.inventory.write``;
adjustments need ``erp.inventory.adjust`` plus above-threshold approval via
``erp.inventory.adjust.approve`` (enforced by the service against the threshold).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_adjustment_authority,
    get_inventory_service,
    get_tenant_context,
    require_permission,
)
from core.core.permissions import (
    ERP_INVENTORY_ADJUST,
    ERP_INVENTORY_READ,
    ERP_INVENTORY_WRITE,
)
from core.features.inventory.schemas import (
    AlertResponse,
    ProductCreate,
    ProductResponse,
    StockAdjustmentCreate,
    StockLevelResponse,
    StockMovementResponse,
    StockTransferCreate,
    TransferResponse,
    WarehouseCreate,
    WarehouseResponse,
    money_input,
)
from skyrict_common.pagination import PaginationParams
from skyrict_common.schemas import ListResponse, PaginationMeta, ResponseEnvelope

if TYPE_CHECKING:
    from core.features.inventory.service import InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])

# Module-level permission dependency singletons (§7.3) so the factory runs once.
_require_inventory_read = require_permission(ERP_INVENTORY_READ)
_require_inventory_write = require_permission(ERP_INVENTORY_WRITE)
_require_inventory_adjust = require_permission(ERP_INVENTORY_ADJUST)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------


@router.get("/products", response_model=ResponseEnvelope[ListResponse[ProductResponse]])
async def list_products(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None),
    _: dict[str, object] = Depends(_require_inventory_read),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[ListResponse[ProductResponse]]:
    """List products (active by default; ``?category=`` filters)."""
    params = PaginationParams.create(page, page_size)
    products = await service.list_products(
        tenant_id, category=category, offset=params.offset, limit=params.limit
    )
    total = await service.count_products(tenant_id, category=category)
    return ResponseEnvelope(
        data=ListResponse(
            data=[ProductResponse.from_entity(p) for p in products],
            meta=PaginationMeta.create(total=total, page=params.page, page_size=params.page_size),
        )
    )


@router.post("/products", response_model=ResponseEnvelope[ProductResponse])
async def create_product(
    body: ProductCreate,
    _: dict[str, object] = Depends(_require_inventory_write),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[ProductResponse]:
    """Create a product (SKU must be unique within the tenant)."""
    product = await service.create_product(
        tenant_id,
        sku=body.sku,
        name=body.name,
        category=body.category,
        unit=body.unit,
        cost_price=money_input(body.cost_price),
        sell_price=money_input(body.sell_price),
        reorder_point=body.reorder_point,
    )
    return ResponseEnvelope(data=ProductResponse.from_entity(product), message="Product created")


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------


@router.get("/warehouses", response_model=ResponseEnvelope[ListResponse[WarehouseResponse]])
async def list_warehouses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict[str, object] = Depends(_require_inventory_read),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[ListResponse[WarehouseResponse]]:
    """List warehouses in the routed tenant."""
    params = PaginationParams.create(page, page_size)
    warehouses = await service.list_warehouses(tenant_id, offset=params.offset, limit=params.limit)
    total = await service.count_warehouses(tenant_id)
    return ResponseEnvelope(
        data=ListResponse(
            data=[WarehouseResponse.from_entity(w) for w in warehouses],
            meta=PaginationMeta.create(total=total, page=params.page, page_size=params.page_size),
        )
    )


@router.post("/warehouses", response_model=ResponseEnvelope[WarehouseResponse])
async def create_warehouse(
    body: WarehouseCreate,
    _: dict[str, object] = Depends(_require_inventory_write),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[WarehouseResponse]:
    """Create a warehouse in the routed tenant."""
    warehouse = await service.create_warehouse(tenant_id, name=body.name, location=body.location)
    return ResponseEnvelope(
        data=WarehouseResponse.from_entity(warehouse), message="Warehouse created"
    )


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------


@router.get("/stock", response_model=ResponseEnvelope[ListResponse[StockLevelResponse]])
async def list_stock_levels(
    product_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict[str, object] = Depends(_require_inventory_read),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[ListResponse[StockLevelResponse]]:
    """List current stock levels, optionally filtered by product/warehouse."""
    from uuid import UUID

    params = PaginationParams.create(page, page_size)
    pid = UUID(product_id) if product_id else None
    wid = UUID(warehouse_id) if warehouse_id else None
    levels = await service.list_stock_levels(
        tenant_id,
        product_id=pid,
        warehouse_id=wid,
        offset=params.offset,
        limit=params.limit,
    )
    total = await service.count_stock_levels(tenant_id, product_id=pid, warehouse_id=wid)
    return ResponseEnvelope(
        data=ListResponse(
            data=[StockLevelResponse.from_entity(level) for level in levels],
            meta=PaginationMeta.create(total=total, page=params.page, page_size=params.page_size),
        )
    )


@router.post(
    "/stock/adjustments",
    response_model=ResponseEnvelope[StockMovementResponse],
    status_code=201,
)
async def adjust_stock(
    body: StockAdjustmentCreate,
    _: dict[str, object] = Depends(_require_inventory_adjust),
    approved: bool = Depends(get_adjustment_authority),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[StockMovementResponse]:
    """Record a signed stock adjustment (idempotent per ``ref_id`` + warehouse)."""
    movement = await service.adjust_stock(
        tenant_id,
        product_id=body.product_id,
        warehouse_id=body.warehouse_id,
        qty=body.qty,
        reason=body.reason,
        ref_id=body.ref_id,
        approved=approved,
    )
    return ResponseEnvelope(
        data=StockMovementResponse.from_entity(movement), message="Stock adjusted"
    )


@router.post(
    "/stock/transfers",
    response_model=ResponseEnvelope[TransferResponse],
    status_code=201,
)
async def transfer_stock(
    body: StockTransferCreate,
    _: dict[str, object] = Depends(_require_inventory_write),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[TransferResponse]:
    """Move stock between two warehouses atomically (2 movements or none)."""
    out_movement, in_movement = await service.transfer_stock(
        tenant_id,
        product_id=body.product_id,
        from_warehouse_id=body.from_warehouse_id,
        to_warehouse_id=body.to_warehouse_id,
        qty=body.qty,
        ref_id=body.ref_id,
    )
    return ResponseEnvelope(
        data=TransferResponse.from_entities(out_movement, in_movement),
        message="Stock transferred",
    )


@router.get(
    "/stock/movements",
    response_model=ResponseEnvelope[ListResponse[StockMovementResponse]],
)
async def list_movements(
    product_id: str | None = Query(default=None),
    warehouse_id: str | None = Query(default=None),
    movement_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict[str, object] = Depends(_require_inventory_read),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[ListResponse[StockMovementResponse]]:
    """List immutable ledger entries, newest first."""
    from uuid import UUID

    from core.domain.value_objects import StockMovementType

    params = PaginationParams.create(page, page_size)
    pid = UUID(product_id) if product_id else None
    wid = UUID(warehouse_id) if warehouse_id else None
    mtype = StockMovementType(movement_type) if movement_type else None
    movements = await service.list_movements(
        tenant_id,
        product_id=pid,
        warehouse_id=wid,
        movement_type=mtype,
        offset=params.offset,
        limit=params.limit,
    )
    total = await service.count_movements(
        tenant_id, product_id=pid, warehouse_id=wid, movement_type=mtype
    )
    return ResponseEnvelope(
        data=ListResponse(
            data=[StockMovementResponse.from_entity(m) for m in movements],
            meta=PaginationMeta.create(total=total, page=params.page, page_size=params.page_size),
        )
    )


@router.get("/alerts", response_model=ResponseEnvelope[ListResponse[AlertResponse]])
async def list_alerts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict[str, object] = Depends(_require_inventory_read),
    tenant_id: str = Depends(get_tenant_context),
    service: InventoryService = Depends(get_inventory_service),
) -> ResponseEnvelope[ListResponse[AlertResponse]]:
    """List products currently at or below their reorder point."""
    params = PaginationParams.create(page, page_size)
    alerts = await service.list_alerts(tenant_id, offset=params.offset, limit=params.limit)
    total = await service.count_alerts(tenant_id)
    return ResponseEnvelope(
        data=ListResponse(
            data=[AlertResponse.from_entities(level, product) for level, product in alerts],
            meta=PaginationMeta.create(total=total, page=params.page, page_size=params.page_size),
        )
    )
