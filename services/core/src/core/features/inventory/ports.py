"""Inventory repository port — persistence contract for the inventory feature.

Declares what the repository must offer so services depend on this Protocol
(hexagonal "port") rather than the concrete SQLAlchemy implementation. There is
deliberately NO update/delete for stock movements: the ledger is immutable.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Protocol

from core.domain.entities import Product, StockLevel, StockMovement, Warehouse


class InventoryRepositoryPort(Protocol):
    """Persistence contract for products, warehouses, stock levels, movements."""

    # --- Products (soft-delete via is_active = false) ---
    async def create_product(self, product: Product) -> Product: ...

    async def get_product(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Product | None: ...

    async def deactivate_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Product | None: ...

    async def list_products(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[Product]: ...

    # --- Warehouses (soft-delete via is_active = false) ---
    async def create_warehouse(self, warehouse: Warehouse) -> Warehouse: ...

    async def get_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None: ...

    async def deactivate_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None: ...

    async def list_warehouses(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[Warehouse]: ...

    # --- Stock levels (materialized from the ledger) ---
    async def get_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> StockLevel | None: ...

    async def recompute_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> StockLevel: ...

    # --- Movements (immutable ledger — no update, no delete) ---
    async def add_movement(self, movement: StockMovement) -> StockMovement: ...

    async def get_movement_by_ref(
        self,
        ref_type: str,
        ref_id: str,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> StockMovement | None: ...

    async def list_movements(
        self,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> Sequence[StockMovement]: ...
