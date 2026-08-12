"""Inventory repository — DB operations for products, warehouses, stock, movements.

Stock is the ledger: ``add_movement`` appends an immutable movement row and then
recomputes the materialized ``erp_stock_levels`` row from the ledger in the SAME
transaction. The level's CHECK constraints (``qty_on_hand >= 0`` and
``0 <= qty_reserved <= qty_on_hand``) are evaluated by the database when the
materialized row is written, so an oversell or over-reservation fails the whole
transaction — including the movement insert — independent of service logic.

All probes are tenant-scoped: lookups take an explicit ``tenant_id`` and every
session is additionally bound by RLS (``app.current_tenant_id``), so a tenant
can never read or write another tenant's rows at either layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import case, func, select

from core.domain.entities import Product, StockLevel, StockMovement, Warehouse
from core.domain.value_objects import Money, StockMovementType
from core.features.inventory.models.product import ErpProductModel
from core.features.inventory.models.stock_level import ErpStockLevelModel
from core.features.inventory.models.stock_movement import ErpStockMovementModel
from core.features.inventory.models.warehouse import ErpWarehouseModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Movements that feed qty_reserved (and are EXCLUDED from qty_on_hand).
_RESERVATION_TYPES = (StockMovementType.RESERVATION, StockMovementType.RELEASE)


def _product_to_orm(product: Product) -> ErpProductModel:
    kwargs: dict[str, object] = {
        "tenant_id": product.tenant_id,
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "unit": product.unit,
        "cost_price": product.cost_price.amount,
        "cost_currency_code": product.cost_price.currency,
        "sell_price": product.sell_price.amount,
        "sell_currency_code": product.sell_price.currency,
        "reorder_point": product.reorder_point,
        "is_active": product.is_active,
    }
    if product.id is not None:
        kwargs["id"] = product.id
    return ErpProductModel(**kwargs)


def _product_from_orm(model: ErpProductModel) -> Product:
    return Product(
        id=model.id,
        tenant_id=model.tenant_id,
        sku=model.sku,
        name=model.name,
        category=model.category,
        unit=model.unit,
        cost_price=Money(model.cost_price, model.cost_currency_code),
        sell_price=Money(model.sell_price, model.sell_currency_code),
        reorder_point=model.reorder_point,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _warehouse_to_orm(warehouse: Warehouse) -> ErpWarehouseModel:
    kwargs: dict[str, object] = {
        "tenant_id": warehouse.tenant_id,
        "name": warehouse.name,
        "location": warehouse.location,
        "is_active": warehouse.is_active,
    }
    if warehouse.id is not None:
        kwargs["id"] = warehouse.id
    return ErpWarehouseModel(**kwargs)


def _warehouse_from_orm(model: ErpWarehouseModel) -> Warehouse:
    return Warehouse(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        location=model.location,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _stock_level_from_orm(model: ErpStockLevelModel) -> StockLevel:
    return StockLevel(
        id=model.id,
        tenant_id=model.tenant_id,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        qty_on_hand=model.qty_on_hand,
        qty_reserved=model.qty_reserved,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _stock_movement_from_orm(model: ErpStockMovementModel) -> StockMovement:
    return StockMovement(
        id=model.id,
        tenant_id=model.tenant_id,
        product_id=model.product_id,
        warehouse_id=model.warehouse_id,
        movement_type=model.movement_type,
        qty=model.qty,
        ref_type=model.ref_type,
        ref_id=model.ref_id,
        created_at=model.created_at,
    )


class InventoryRepository:
    """Concrete SQLAlchemy implementation of :class:`InventoryRepositoryPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    async def create_product(self, product: Product) -> Product:
        model = _product_to_orm(product)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _product_from_orm(model)

    async def get_product(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Product | None:
        stmt = select(ErpProductModel).where(
            ErpProductModel.tenant_id == tenant_id,
            ErpProductModel.id == product_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _product_from_orm(model) if model is not None else None

    async def deactivate_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Product | None:
        stmt = select(ErpProductModel).where(
            ErpProductModel.tenant_id == tenant_id,
            ErpProductModel.id == product_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.is_active = False
        await self.session.flush()
        await self.session.refresh(model)
        return _product_from_orm(model)

    async def list_products(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[Product]:
        stmt = select(ErpProductModel).where(ErpProductModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(ErpProductModel.is_active.is_(True))
        stmt = stmt.order_by(ErpProductModel.sku)
        result = await self.session.execute(stmt)
        return [_product_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------

    async def create_warehouse(self, warehouse: Warehouse) -> Warehouse:
        model = _warehouse_to_orm(warehouse)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _warehouse_from_orm(model)

    async def get_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None:
        stmt = select(ErpWarehouseModel).where(
            ErpWarehouseModel.tenant_id == tenant_id,
            ErpWarehouseModel.id == warehouse_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _warehouse_from_orm(model) if model is not None else None

    async def deactivate_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None:
        stmt = select(ErpWarehouseModel).where(
            ErpWarehouseModel.tenant_id == tenant_id,
            ErpWarehouseModel.id == warehouse_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.is_active = False
        await self.session.flush()
        await self.session.refresh(model)
        return _warehouse_from_orm(model)

    async def list_warehouses(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> Sequence[Warehouse]:
        stmt = select(ErpWarehouseModel).where(ErpWarehouseModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(ErpWarehouseModel.is_active.is_(True))
        stmt = stmt.order_by(ErpWarehouseModel.name)
        result = await self.session.execute(stmt)
        return [_warehouse_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Stock levels
    # ------------------------------------------------------------------

    async def get_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> StockLevel | None:
        stmt = select(ErpStockLevelModel).where(
            ErpStockLevelModel.tenant_id == tenant_id,
            ErpStockLevelModel.product_id == product_id,
            ErpStockLevelModel.warehouse_id == warehouse_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _stock_level_from_orm(model) if model is not None else None

    async def recompute_stock_level(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> StockLevel:
        """Rebuild the materialized level from the ledger for one product/warehouse.

        ``qty_on_hand`` = sum of all non-reservation movements; ``qty_reserved``
        = net of reservation/release movements. Writing the result runs the
        table's CHECK constraints, so over-reservation / negative stock raises
        here and rolls back the enclosing transaction.
        """
        reservation_types = tuple(_RESERVATION_TYPES)
        on_hand_expr = func.coalesce(
            func.sum(
                case(
                    (
                        ~ErpStockMovementModel.movement_type.in_(reservation_types),
                        ErpStockMovementModel.qty,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        reserved_expr = func.coalesce(
            func.sum(
                case(
                    (
                        ErpStockMovementModel.movement_type.in_(reservation_types),
                        ErpStockMovementModel.qty,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        stmt = select(on_hand_expr.label("on_hand"), reserved_expr.label("reserved")).where(
            ErpStockMovementModel.tenant_id == tenant_id,
            ErpStockMovementModel.product_id == product_id,
            ErpStockMovementModel.warehouse_id == warehouse_id,
        )
        row = (await self.session.execute(stmt)).one()
        qty_on_hand = Decimal(row.on_hand)
        qty_reserved = Decimal(row.reserved)

        stmt = select(ErpStockLevelModel).where(
            ErpStockLevelModel.tenant_id == tenant_id,
            ErpStockLevelModel.product_id == product_id,
            ErpStockLevelModel.warehouse_id == warehouse_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()

        if model is None:
            model = ErpStockLevelModel(
                tenant_id=tenant_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                qty_on_hand=qty_on_hand,
                qty_reserved=qty_reserved,
            )
            self.session.add(model)
        else:
            model.qty_on_hand = qty_on_hand
            model.qty_reserved = qty_reserved

        await self.session.flush()
        await self.session.refresh(model)
        return _stock_level_from_orm(model)

    # ------------------------------------------------------------------
    # Movements (immutable — no update, no delete)
    # ------------------------------------------------------------------

    async def add_movement(self, movement: StockMovement) -> StockMovement:
        """Insert an immutable ledger row and recompute the level atomically.

        Idempotent per ``(tenant_id, ref_type, ref_id, warehouse_id)``: if the
        ref was already applied to this warehouse, the existing movement is
        returned instead of a duplicate insert.
        """
        existing = await self.get_movement_by_ref(
            movement.ref_type,
            movement.ref_id,
            movement.warehouse_id,
            movement.tenant_id,
        )
        if existing is not None:
            return existing

        model = ErpStockMovementModel(
            tenant_id=movement.tenant_id,
            product_id=movement.product_id,
            warehouse_id=movement.warehouse_id,
            movement_type=movement.movement_type,
            qty=movement.qty,
            ref_type=movement.ref_type,
            ref_id=movement.ref_id,
        )
        if movement.id is not None:
            model.id = movement.id
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)

        await self.recompute_stock_level(
            movement.product_id, movement.warehouse_id, movement.tenant_id
        )
        return _stock_movement_from_orm(model)

    async def get_movement_by_ref(
        self,
        ref_type: str,
        ref_id: str,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> StockMovement | None:
        stmt = select(ErpStockMovementModel).where(
            ErpStockMovementModel.tenant_id == tenant_id,
            ErpStockMovementModel.ref_type == ref_type,
            ErpStockMovementModel.ref_id == ref_id,
            ErpStockMovementModel.warehouse_id == warehouse_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _stock_movement_from_orm(model) if model is not None else None

    async def list_movements(
        self,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> Sequence[StockMovement]:
        stmt = (
            select(ErpStockMovementModel)
            .where(
                ErpStockMovementModel.tenant_id == tenant_id,
                ErpStockMovementModel.product_id == product_id,
                ErpStockMovementModel.warehouse_id == warehouse_id,
            )
            .order_by(ErpStockMovementModel.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_stock_movement_from_orm(model) for model in result.scalars().all()]
