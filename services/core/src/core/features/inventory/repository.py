"""Inventory repository - DB operations for products, warehouses, stock, movements.

Stock is the ledger: ``add_movement`` appends an immutable movement row and then
recomputes the materialized ``erp_stock_levels`` row from the ledger in the SAME
transaction. The level's CHECK constraints (``qty_on_hand >= 0`` and
``0 <= qty_reserved <= qty_on_hand``) are evaluated by the database when the
materialized row is written, so an oversell or over-reservation fails the whole
transaction - including the movement insert - independent of service logic.

All probes are tenant-scoped: lookups take an explicit ``tenant_id`` and every
session is additionally bound by RLS (``app.current_tenant_id``), so a tenant
can never read or write another tenant's rows at either layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.engine import CursorResult

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

# Sentinel distinguishing "field not in the PATCH body" from "clear to null".
_UNSET: object = object()


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

    async def get_product_by_sku(self, sku: str, tenant_id: uuid.UUID) -> Product | None:
        stmt = select(ErpProductModel).where(
            ErpProductModel.tenant_id == tenant_id,
            ErpProductModel.sku == sku,
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

    async def reactivate_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Product | None:
        stmt = select(ErpProductModel).where(
            ErpProductModel.tenant_id == tenant_id,
            ErpProductModel.id == product_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.is_active = True
        await self.session.flush()
        await self.session.refresh(model)
        return _product_from_orm(model)

    async def update_product(
        self,
        product_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        sku: str | object = _UNSET,
        name: str | object = _UNSET,
        category: str | object | None = _UNSET,
        unit: str | object | None = _UNSET,
        cost_price: Money | object = _UNSET,
        sell_price: Money | object = _UNSET,
        reorder_point: Decimal | object = _UNSET,
    ) -> Product | None:
        stmt = select(ErpProductModel).where(
            ErpProductModel.tenant_id == tenant_id,
            ErpProductModel.id == product_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        if sku is not _UNSET:
            model.sku = cast("str", sku)
        if name is not _UNSET:
            model.name = cast("str", name)
        if category is not _UNSET:
            model.category = cast("str | None", category)
        if unit is not _UNSET:
            model.unit = cast("str | None", unit)
        if cost_price is not _UNSET:
            model.cost_price = cast("Money", cost_price).amount
            model.cost_currency_code = cast("Money", cost_price).currency
        if sell_price is not _UNSET:
            model.sell_price = cast("Money", sell_price).amount
            model.sell_currency_code = cast("Money", sell_price).currency
        if reorder_point is not _UNSET:
            model.reorder_point = cast("Decimal", reorder_point)
        await self.session.flush()
        await self.session.refresh(model)
        return _product_from_orm(model)

    async def list_products(
        self,
        tenant_id: uuid.UUID,
        *,
        include_inactive: bool = False,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Product]:
        stmt = select(ErpProductModel).where(ErpProductModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(ErpProductModel.is_active.is_(True))
        if category:
            stmt = stmt.where(ErpProductModel.category == category)
        stmt = stmt.order_by(ErpProductModel.sku).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return [_product_from_orm(model) for model in result.scalars().all()]

    async def count_products(
        self,
        tenant_id: uuid.UUID,
        *,
        include_inactive: bool = False,
        category: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ErpProductModel)
            .where(ErpProductModel.tenant_id == tenant_id)
        )
        if not include_inactive:
            stmt = stmt.where(ErpProductModel.is_active.is_(True))
        if category:
            stmt = stmt.where(ErpProductModel.category == category)
        return int((await self.session.execute(stmt)).scalar_one())

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

    async def reactivate_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Warehouse | None:
        stmt = select(ErpWarehouseModel).where(
            ErpWarehouseModel.tenant_id == tenant_id,
            ErpWarehouseModel.id == warehouse_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        model.is_active = True
        await self.session.flush()
        await self.session.refresh(model)
        return _warehouse_from_orm(model)

    async def update_warehouse(
        self,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        name: str | object = _UNSET,
        location: str | object | None = _UNSET,
    ) -> Warehouse | None:
        stmt = select(ErpWarehouseModel).where(
            ErpWarehouseModel.tenant_id == tenant_id,
            ErpWarehouseModel.id == warehouse_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        if name is not _UNSET:
            model.name = cast("str", name)
        if location is not _UNSET:
            model.location = cast("str | None", location)
        await self.session.flush()
        await self.session.refresh(model)
        return _warehouse_from_orm(model)

    async def list_warehouses(
        self,
        tenant_id: uuid.UUID,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Warehouse]:
        stmt = select(ErpWarehouseModel).where(ErpWarehouseModel.tenant_id == tenant_id)
        if not include_inactive:
            stmt = stmt.where(ErpWarehouseModel.is_active.is_(True))
        stmt = stmt.order_by(ErpWarehouseModel.name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return [_warehouse_from_orm(model) for model in result.scalars().all()]

    async def count_warehouses(
        self, tenant_id: uuid.UUID, *, include_inactive: bool = False
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ErpWarehouseModel)
            .where(ErpWarehouseModel.tenant_id == tenant_id)
        )
        if not include_inactive:
            stmt = stmt.where(ErpWarehouseModel.is_active.is_(True))
        return int((await self.session.execute(stmt)).scalar_one())

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

    async def list_stock_levels(
        self,
        tenant_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[StockLevel]:
        stmt = select(ErpStockLevelModel).where(ErpStockLevelModel.tenant_id == tenant_id)
        if product_id is not None:
            stmt = stmt.where(ErpStockLevelModel.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(ErpStockLevelModel.warehouse_id == warehouse_id)
        stmt = (
            stmt.order_by(ErpStockLevelModel.product_id, ErpStockLevelModel.warehouse_id)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_stock_level_from_orm(model) for model in result.scalars().all()]

    async def count_stock_levels(
        self,
        tenant_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ErpStockLevelModel)
            .where(ErpStockLevelModel.tenant_id == tenant_id)
        )
        if product_id is not None:
            stmt = stmt.where(ErpStockLevelModel.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(ErpStockLevelModel.warehouse_id == warehouse_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def sum_stock_by_product(
        self, product_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> tuple[Decimal, Decimal]:
        """Total on-hand / reserved quantity for a product across warehouses."""
        stmt = select(
            func.coalesce(func.sum(ErpStockLevelModel.qty_on_hand), 0).label("on_hand"),
            func.coalesce(func.sum(ErpStockLevelModel.qty_reserved), 0).label("reserved"),
        ).where(
            ErpStockLevelModel.tenant_id == tenant_id,
            ErpStockLevelModel.product_id == product_id,
        )
        row = (await self.session.execute(stmt)).one()
        return Decimal(row.on_hand), Decimal(row.reserved)

    async def sum_stock_by_warehouse(
        self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> tuple[Decimal, Decimal]:
        """Total on-hand / reserved quantity for a warehouse across products."""
        stmt = select(
            func.coalesce(func.sum(ErpStockLevelModel.qty_on_hand), 0).label("on_hand"),
            func.coalesce(func.sum(ErpStockLevelModel.qty_reserved), 0).label("reserved"),
        ).where(
            ErpStockLevelModel.tenant_id == tenant_id,
            ErpStockLevelModel.warehouse_id == warehouse_id,
        )
        row = (await self.session.execute(stmt)).one()
        return Decimal(row.on_hand), Decimal(row.reserved)

    async def list_low_stock(
        self,
        tenant_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[tuple[StockLevel, Product]]:
        """Levels currently at or below their product's reorder point."""
        stmt = (
            select(ErpStockLevelModel, ErpProductModel)
            .join(
                ErpProductModel,
                and_(
                    ErpProductModel.tenant_id == ErpStockLevelModel.tenant_id,
                    ErpProductModel.id == ErpStockLevelModel.product_id,
                ),
            )
            .where(
                ErpStockLevelModel.tenant_id == tenant_id,
                ErpProductModel.is_active.is_(True),
                ErpStockLevelModel.qty_on_hand <= ErpProductModel.reorder_point,
            )
            .order_by(ErpStockLevelModel.qty_on_hand.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            (_stock_level_from_orm(level), _product_from_orm(product))
            for level, product in result.all()
        ]

    async def count_low_stock(self, tenant_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(ErpStockLevelModel)
            .join(
                ErpProductModel,
                and_(
                    ErpProductModel.tenant_id == ErpStockLevelModel.tenant_id,
                    ErpProductModel.id == ErpStockLevelModel.product_id,
                ),
            )
            .where(
                ErpStockLevelModel.tenant_id == tenant_id,
                ErpProductModel.is_active.is_(True),
                ErpStockLevelModel.qty_on_hand <= ErpProductModel.reorder_point,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # Guarded reservation updates (atomic row-lock + CHECK fallback)
    #
    # Reservation mutations run a conditional UPDATE on the materialized
    # level FIRST: the ``WHERE`` re-evaluates against the freshly locked row,
    # so concurrent reserve/release calls serialize on the row lock and the
    # invariant ``qty_reserved <= qty_on_hand`` is enforced before any ledger
    # row is written. The ledger movement is then appended and the level
    # recomputed, keeping the projection consistent with the ledger. The DB
    # CHECK constraint remains the final defense if the guard is bypassed.
    # ------------------------------------------------------------------

    async def apply_reservation_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID
    ) -> bool:
        """Atomically add ``qty`` to qty_reserved iff the result stays <= qty_on_hand."""
        stmt = (
            update(ErpStockLevelModel)
            .where(
                ErpStockLevelModel.tenant_id == tenant_id,
                ErpStockLevelModel.product_id == product_id,
                ErpStockLevelModel.warehouse_id == warehouse_id,
                ErpStockLevelModel.qty_reserved + qty <= ErpStockLevelModel.qty_on_hand,
            )
            .values(qty_reserved=ErpStockLevelModel.qty_reserved + qty)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        return result.rowcount > 0

    async def apply_release_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID
    ) -> bool:
        """Atomically subtract ``qty`` from qty_reserved iff the result stays >= 0."""
        stmt = (
            update(ErpStockLevelModel)
            .where(
                ErpStockLevelModel.tenant_id == tenant_id,
                ErpStockLevelModel.product_id == product_id,
                ErpStockLevelModel.warehouse_id == warehouse_id,
                ErpStockLevelModel.qty_reserved - qty >= 0,
            )
            .values(qty_reserved=ErpStockLevelModel.qty_reserved - qty)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        return result.rowcount > 0

    async def apply_consume_qty(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, qty: Decimal, tenant_id: uuid.UUID
    ) -> bool:
        """Atomically release ``qty`` from qty_reserved (fulfilment step)."""
        return await self.apply_release_qty(product_id, warehouse_id, qty, tenant_id)

    # ------------------------------------------------------------------
    # Movements (immutable - no update, no delete)
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
        tenant_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: StockMovementType | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[StockMovement]:
        stmt = select(ErpStockMovementModel).where(ErpStockMovementModel.tenant_id == tenant_id)
        if product_id is not None:
            stmt = stmt.where(ErpStockMovementModel.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(ErpStockMovementModel.warehouse_id == warehouse_id)
        if movement_type is not None:
            stmt = stmt.where(ErpStockMovementModel.movement_type == movement_type)
        stmt = stmt.order_by(ErpStockMovementModel.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return [_stock_movement_from_orm(model) for model in result.scalars().all()]

    async def count_movements(
        self,
        tenant_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: StockMovementType | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ErpStockMovementModel)
            .where(ErpStockMovementModel.tenant_id == tenant_id)
        )
        if product_id is not None:
            stmt = stmt.where(ErpStockMovementModel.product_id == product_id)
        if warehouse_id is not None:
            stmt = stmt.where(ErpStockMovementModel.warehouse_id == warehouse_id)
        if movement_type is not None:
            stmt = stmt.where(ErpStockMovementModel.movement_type == movement_type)
        return int((await self.session.execute(stmt)).scalar_one())

    async def commit(self) -> None:
        """Commit the current transaction - services own the transaction lifecycle."""
        await self.session.commit()
