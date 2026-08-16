"""Inventory service — §4 business rules + §5.4 reservation port.

The service owns the transaction lifecycle. Every mutating method runs its
checks and ledger writes inside ONE transaction, calls ``inventory_repo.commit()``,
and only THEN writes audit rows and emits events. A rollback can therefore never
produce a phantom audit/event, and a committed mutation stays observable even if
the audit write fails afterwards (at-least-once, matching identity's audit flow).

Rules implemented (see docs/modules/inventory-warehouse.md §4):
  Rule 1 — stock is a ledger: every change writes exactly one (or one pair of)
           immutable movement rows; ``qty_on_hand`` is recomputed from the
           ledger inside the same transaction.
  Rule 2 — no negative stock: the service pre-checks ``before + qty >= 0`` and
           raises ``InsufficientStockError`` (409); the DB CHECK is the backstop
           that serializes concurrent writers.
  Rule 3 — transfers are atomic: two movements (source ``-qty``, destination
           ``+qty``) share one ``ref_id`` in a single transaction — or none.
  Rule 4 — reorder alerts fire ONCE per breach crossing: only when the level
           transitions from ``> reorder_point`` to ``<= reorder_point``.

Idempotency (spec §10.2) is probe-based: ``(ref_type, ref_id, warehouse_id)``
is unique per tenant, so replaying a ref raises ``MovementImmutableError`` (409)
instead of double-posting.

Reservation lifecycle (§5.4): ``reserve_stock`` / ``release_reservation`` /
``fulfil_order`` share the caller's logical ``ref_id`` but write step-scoped
ledger refs (``<ref_id>:reserve``, ``:release``, ``:issue``) so all three steps
of one order line can coexist under the movement unique constraint. Invariants:
``qty_reserved <= qty_on_hand`` (else 409) and ``qty_reserved >= 0``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from core.audit_events import (
    PRODUCT_CREATED,
    STOCK_ADJUSTED,
    STOCK_REORDER_ALERTED,
    STOCK_TRANSFERRED,
    WAREHOUSE_CREATED,
)
from core.core.config import settings
from core.core.exceptions import (
    DuplicateSkuError,
    InsufficientStockError,
    MovementImmutableError,
    TransferRequiresDistinctWarehousesError,
)
from core.core.tenant_context import TenantContext
from core.domain.entities import Product, SalesOrderLine, StockLevel, StockMovement, Warehouse
from core.domain.value_objects import Money, StockMovementType
from core.features.inventory.events.producers import emit_stock_level_changed
from skyrict_common.exceptions import NotFoundError, PermissionDeniedError, ValidationError

if TYPE_CHECKING:
    from core.features.audit.service import AuditService
    from core.features.inventory.ports import InventoryRepositoryPort

# Ledger refs for the reservation lifecycle steps (§5.4). Distinct steps of one
# order line must not collide under the UNIQUE (ref_type, ref_id, warehouse_id).
_STEP_RESERVE = "reserve"
_STEP_RELEASE = "release"
_STEP_ISSUE = "issue"

# Non-ledger mutation types whose on-hand change is worth broadcasting.
_ON_HAND_MUTATIONS = frozenset(
    {StockMovementType.ADJUSTMENT, StockMovementType.TRANSFER, StockMovementType.ISSUE}
)


def _as_uuid(value: str | uuid.UUID) -> uuid.UUID:
    return uuid.UUID(value) if isinstance(value, str) else value


def _step_ref(ref_id: str, step: str) -> str:
    """Ledger-safe ref for a reservation lifecycle step."""
    return f"{ref_id}:{step}"


class InventoryService:
    """Implements :class:`InventoryServicePort` and :class:`StockReservationPort`.

    Single class implements both ports — CRM calls reservation methods on the
    same service object the HTTP router consumes (spec §5.4: "same service
    object or an injected port").
    """

    def __init__(
        self,
        inventory_repo: InventoryRepositoryPort,
        audit_service: AuditService,
        *,
        approve_threshold: Decimal | None = None,
    ) -> None:
        self.inventory_repo = inventory_repo
        self.audit_service = audit_service
        self.approve_threshold = (
            settings.INVENTORY_ADJUST_APPROVE_THRESHOLD
            if approve_threshold is None
            else approve_threshold
        )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _audit(
        self,
        *,
        tenant_id: str | uuid.UUID,
        action: str,
        target: str,
        details: dict[str, object] | None = None,
    ) -> None:
        await self.audit_service.log(
            action=action,
            target=target,
            user_id=TenantContext.get_user_id(),
            tenant_id=str(tenant_id),
            details=details,
        )

    async def _reject_replay(
        self,
        ref_type: str,
        ref_id: str,
        warehouse_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> None:
        existing = await self.inventory_repo.get_movement_by_ref(
            ref_type, ref_id, warehouse_id, tenant_id
        )
        if existing is not None:
            raise MovementImmutableError()

    async def _require_product(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Product:
        product = await self.inventory_repo.get_product(product_id, tenant_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found in tenant {tenant_id}")
        return product

    async def _require_warehouse(self, warehouse_id: uuid.UUID, tenant_id: uuid.UUID) -> Warehouse:
        warehouse = await self.inventory_repo.get_warehouse(warehouse_id, tenant_id)
        if warehouse is None:
            raise NotFoundError(f"Warehouse {warehouse_id} not found in tenant {tenant_id}")
        return warehouse

    async def _current_on_hand(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Decimal:
        level = await self.inventory_repo.get_stock_level(product_id, warehouse_id, tenant_id)
        return level.qty_on_hand if level is not None else Decimal("0")

    async def _current_reserved(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Decimal:
        level = await self.inventory_repo.get_stock_level(product_id, warehouse_id, tenant_id)
        return level.qty_reserved if level is not None else Decimal("0")

    def _assert_non_negative(self, value: Decimal) -> None:
        if value < 0:
            raise InsufficientStockError()

    async def _emit_level_changed(
        self,
        *,
        tenant_id: uuid.UUID,
        product: Product,
        warehouse_id: uuid.UUID,
        before: Decimal,
        after: Decimal,
    ) -> None:
        """Rule 4 — broadcast the level change; fire the alert only on a crossing."""
        assert product.id is not None
        breach_crossed = before > product.reorder_point and after <= product.reorder_point
        await emit_stock_level_changed(
            tenant_id=str(tenant_id),
            product_id=str(product.id),
            warehouse_id=str(warehouse_id),
            qty_on_hand=after,
            reorder_point=product.reorder_point,
            breach_crossed=breach_crossed,
        )
        if breach_crossed:
            await self._audit(
                tenant_id=tenant_id,
                action=STOCK_REORDER_ALERTED,
                target=f"product:{product.id}",
                details={
                    "product_id": str(product.id),
                    "warehouse_id": str(warehouse_id),
                    "qty_on_hand": str(after),
                    "reorder_point": str(product.reorder_point),
                },
            )

    # ------------------------------------------------------------------
    # Products / warehouses
    # ------------------------------------------------------------------

    async def create_product(
        self,
        tenant_id: str | uuid.UUID,
        *,
        sku: str,
        name: str,
        category: str | None = None,
        unit: str | None = None,
        cost_price: Money | None = None,
        sell_price: Money | None = None,
        reorder_point: Decimal = Decimal("0"),
    ) -> Product:
        tid = _as_uuid(tenant_id)
        if not sku.strip():
            raise ValidationError("Product SKU is required")
        if not name.strip():
            raise ValidationError("Product name is required")
        if reorder_point < 0:
            raise ValidationError("Reorder point cannot be negative")

        existing = await self.inventory_repo.get_product_by_sku(sku, tid)
        if existing is not None:
            raise DuplicateSkuError()

        created = await self.inventory_repo.create_product(
            Product(
                tenant_id=tid,
                sku=sku,
                name=name,
                category=category,
                unit=unit,
                cost_price=cost_price or Money.zero(settings.DEFAULT_CURRENCY),
                sell_price=sell_price or Money.zero(settings.DEFAULT_CURRENCY),
                reorder_point=reorder_point,
            )
        )
        await self.inventory_repo.commit()

        assert created.id is not None
        await self._audit(
            tenant_id=tid,
            action=PRODUCT_CREATED,
            target=f"product:{created.id}",
            details={"sku": sku, "name": name},
        )
        return created

    async def create_warehouse(
        self,
        tenant_id: str | uuid.UUID,
        *,
        name: str,
        location: str | None = None,
    ) -> Warehouse:
        tid = _as_uuid(tenant_id)
        if not name.strip():
            raise ValidationError("Warehouse name is required")

        created = await self.inventory_repo.create_warehouse(
            Warehouse(tenant_id=tid, name=name, location=location)
        )
        await self.inventory_repo.commit()

        assert created.id is not None
        await self._audit(
            tenant_id=tid,
            action=WAREHOUSE_CREATED,
            target=f"warehouse:{created.id}",
            details={"name": name},
        )
        return created

    # ------------------------------------------------------------------
    # Rule 2 — stock adjustments
    # ------------------------------------------------------------------

    async def adjust_stock(
        self,
        tenant_id: str | uuid.UUID,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        qty: Decimal,
        reason: str,
        ref_id: str,
        approved: bool = False,
    ) -> StockMovement:
        tid = _as_uuid(tenant_id)
        if qty == 0:
            raise ValidationError("Adjustment quantity must be non-zero")
        if not reason or not reason.strip():
            raise ValidationError("Adjustment requires a reason")

        # §14.3 — large adjustments need approval (enforced here, decided by the
        # router via erp.inventory.adjust.approve).
        if abs(qty) > self.approve_threshold and not approved:
            raise PermissionDeniedError(
                f"Adjustment of |{qty}| exceeds the approval threshold "
                f"({self.approve_threshold}); erp.inventory.adjust.approve is required"
            )

        await self._reject_replay("adjustment", ref_id, warehouse_id, tid)
        product = await self._require_product(product_id, tid)
        await self._require_warehouse(warehouse_id, tid)

        before = await self._current_on_hand(product_id, warehouse_id, tid)
        self._assert_non_negative(before + qty)

        created = await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=warehouse_id,
                movement_type=StockMovementType.ADJUSTMENT,
                qty=qty,
                ref_type="adjustment",
                ref_id=ref_id,
            )
        )
        await self.inventory_repo.commit()

        assert created.id is not None
        await self._audit(
            tenant_id=tid,
            action=STOCK_ADJUSTED,
            target=f"stock_movement:{created.id}",
            details={
                "product_id": str(product_id),
                "warehouse_id": str(warehouse_id),
                "qty": str(qty),
                "reason": reason,
                "ref_id": ref_id,
            },
        )
        await self._emit_level_changed(
            tenant_id=tid,
            product=product,
            warehouse_id=warehouse_id,
            before=before,
            after=before + qty,
        )
        return created

    # ------------------------------------------------------------------
    # Rule 3 — atomic transfers
    # ------------------------------------------------------------------

    async def transfer_stock(
        self,
        tenant_id: str | uuid.UUID,
        *,
        product_id: uuid.UUID,
        from_warehouse_id: uuid.UUID,
        to_warehouse_id: uuid.UUID,
        qty: Decimal,
        ref_id: str,
    ) -> tuple[StockMovement, StockMovement]:
        tid = _as_uuid(tenant_id)
        if from_warehouse_id == to_warehouse_id:
            raise TransferRequiresDistinctWarehousesError()
        if qty <= 0:
            raise ValidationError("Transfer quantity must be positive")

        await self._reject_replay("transfer", ref_id, from_warehouse_id, tid)
        product = await self._require_product(product_id, tid)
        await self._require_warehouse(from_warehouse_id, tid)
        await self._require_warehouse(to_warehouse_id, tid)

        from_before = await self._current_on_hand(product_id, from_warehouse_id, tid)
        to_before = await self._current_on_hand(product_id, to_warehouse_id, tid)
        self._assert_non_negative(from_before - qty)

        out_movement = await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=from_warehouse_id,
                movement_type=StockMovementType.TRANSFER,
                qty=-qty,
                ref_type="transfer",
                ref_id=ref_id,
            )
        )
        in_movement = await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=to_warehouse_id,
                movement_type=StockMovementType.TRANSFER,
                qty=qty,
                ref_type="transfer",
                ref_id=ref_id,
            )
        )
        await self.inventory_repo.commit()

        assert out_movement.id is not None and in_movement.id is not None
        await self._audit(
            tenant_id=tid,
            action=STOCK_TRANSFERRED,
            target=f"stock_movement:{out_movement.id}",
            details={
                "product_id": str(product_id),
                "from_warehouse_id": str(from_warehouse_id),
                "to_warehouse_id": str(to_warehouse_id),
                "qty": str(qty),
                "ref_id": ref_id,
            },
        )
        # Source level decreases (can cross below the reorder point); the
        # destination only increases, so it can never fire a crossing.
        await self._emit_level_changed(
            tenant_id=tid,
            product=product,
            warehouse_id=from_warehouse_id,
            before=from_before,
            after=from_before - qty,
        )
        await self._emit_level_changed(
            tenant_id=tid,
            product=product,
            warehouse_id=to_warehouse_id,
            before=to_before,
            after=to_before + qty,
        )
        return out_movement, in_movement

    # ------------------------------------------------------------------
    # §5.4 — reservation lifecycle (CRM port)
    # ------------------------------------------------------------------

    async def reserve_stock(
        self,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        qty: Decimal,
        tenant_id: str | uuid.UUID,
        *,
        ref_type: str = "sale_order",
        ref_id: str,
    ) -> StockLevel:
        tid = _as_uuid(tenant_id)
        if qty <= 0:
            raise ValidationError("Reservation quantity must be positive")

        ledger_ref = _step_ref(ref_id, _STEP_RESERVE)
        await self._reject_replay(ref_type, ledger_ref, warehouse_id, tid)
        await self._require_product(product_id, tid)
        await self._require_warehouse(warehouse_id, tid)

        if not await self.inventory_repo.apply_reservation_qty(product_id, warehouse_id, qty, tid):
            raise InsufficientStockError()

        await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=warehouse_id,
                movement_type=StockMovementType.RESERVATION,
                qty=qty,
                ref_type=ref_type,
                ref_id=ledger_ref,
            )
        )
        await self.inventory_repo.commit()

        level = await self.inventory_repo.get_stock_level(product_id, warehouse_id, tid)
        assert level is not None
        return level

    async def release_reservation(
        self,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        qty: Decimal,
        tenant_id: str | uuid.UUID,
        *,
        ref_type: str = "sale_order",
        ref_id: str,
    ) -> StockLevel:
        tid = _as_uuid(tenant_id)
        if qty <= 0:
            raise ValidationError("Release quantity must be positive")

        ledger_ref = _step_ref(ref_id, _STEP_RELEASE)
        await self._reject_replay(ref_type, ledger_ref, warehouse_id, tid)
        await self._require_product(product_id, tid)
        await self._require_warehouse(warehouse_id, tid)

        if not await self.inventory_repo.apply_release_qty(product_id, warehouse_id, qty, tid):
            raise ValidationError("Cannot release more than the reserved quantity")

        await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=warehouse_id,
                movement_type=StockMovementType.RELEASE,
                qty=-qty,
                ref_type=ref_type,
                ref_id=ledger_ref,
            )
        )
        await self.inventory_repo.commit()

        level = await self.inventory_repo.get_stock_level(product_id, warehouse_id, tid)
        assert level is not None
        return level

    async def fulfil_order(
        self,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        qty: Decimal,
        tenant_id: str | uuid.UUID,
        *,
        ref_type: str = "sale_order",
        ref_id: str,
    ) -> StockLevel:
        tid = _as_uuid(tenant_id)
        if qty <= 0:
            raise ValidationError("Fulfilment quantity must be positive")

        product = await self._require_product(product_id, tid)
        await self._require_warehouse(warehouse_id, tid)
        before = await self._current_on_hand(product_id, warehouse_id, tid)

        # Consume the reservation atomically — serializes concurrent fulfils.
        if not await self.inventory_repo.apply_consume_qty(product_id, warehouse_id, qty, tid):
            raise InsufficientStockError()

        # Fulfilment = release the reservation AND write the sale outflow; both
        # are needed for the ledger recompute to settle on reserved = 0.
        await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=warehouse_id,
                movement_type=StockMovementType.RELEASE,
                qty=-qty,
                ref_type=ref_type,
                ref_id=_step_ref(ref_id, _STEP_RELEASE),
            )
        )
        await self.inventory_repo.add_movement(
            StockMovement(
                tenant_id=tid,
                product_id=product_id,
                warehouse_id=warehouse_id,
                movement_type=StockMovementType.ISSUE,
                qty=-qty,
                ref_type=ref_type,
                ref_id=_step_ref(ref_id, _STEP_ISSUE),
            )
        )
        await self.inventory_repo.commit()

        await self._emit_level_changed(
            tenant_id=tid,
            product=product,
            warehouse_id=warehouse_id,
            before=before,
            after=before - qty,
        )

        level = await self.inventory_repo.get_stock_level(product_id, warehouse_id, tid)
        assert level is not None
        return level

    # ------------------------------------------------------------------
    # §5.4 — whole-order reservation lifecycle (bulk, single-commit)
    #
    # The per-line methods above commit after EVERY line, which breaks
    # all-or-nothing atomicity for a multi-line order sharing one request
    # session. These three methods apply the SAME per-line semantics but defer
    # the single commit to the end: a partial order can never be persisted, a
    # rollback touches nothing, and the one commit also persists the sales
    # order state guard that ran just before in the same transaction.
    # ------------------------------------------------------------------

    async def reserve_order(
        self,
        tenant_id: str | uuid.UUID,
        *,
        warehouse_id: uuid.UUID,
        order_id: uuid.UUID,
        lines: Sequence[SalesOrderLine],
        ref_type: str = "sale_order",
    ) -> None:
        """Reserve every line of one order in a SINGLE transaction."""
        tid = _as_uuid(tenant_id)
        ref_id = str(order_id)
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError("Reservation quantity must be positive")
            ledger_ref = _step_ref(ref_id, _STEP_RESERVE)
            await self._reject_replay(ref_type, ledger_ref, warehouse_id, tid)
            await self._require_product(line.product_id, tid)
            await self._require_warehouse(warehouse_id, tid)
            if not await self.inventory_repo.apply_reservation_qty(
                line.product_id, warehouse_id, line.quantity, tid
            ):
                raise InsufficientStockError()
            await self.inventory_repo.add_movement(
                StockMovement(
                    tenant_id=tid,
                    product_id=line.product_id,
                    warehouse_id=warehouse_id,
                    movement_type=StockMovementType.RESERVATION,
                    qty=line.quantity,
                    ref_type=ref_type,
                    ref_id=ledger_ref,
                )
            )
        await self.inventory_repo.commit()

    async def release_order(
        self,
        tenant_id: str | uuid.UUID,
        *,
        warehouse_id: uuid.UUID,
        order_id: uuid.UUID,
        lines: Sequence[SalesOrderLine],
        ref_type: str = "sale_order",
    ) -> None:
        """Release every reserved line of one order in a SINGLE transaction."""
        tid = _as_uuid(tenant_id)
        ref_id = str(order_id)
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError("Release quantity must be positive")
            ledger_ref = _step_ref(ref_id, _STEP_RELEASE)
            await self._reject_replay(ref_type, ledger_ref, warehouse_id, tid)
            await self._require_product(line.product_id, tid)
            await self._require_warehouse(warehouse_id, tid)
            if not await self.inventory_repo.apply_release_qty(
                line.product_id, warehouse_id, line.quantity, tid
            ):
                raise ValidationError("Cannot release more than the reserved quantity")
            await self.inventory_repo.add_movement(
                StockMovement(
                    tenant_id=tid,
                    product_id=line.product_id,
                    warehouse_id=warehouse_id,
                    movement_type=StockMovementType.RELEASE,
                    qty=-line.quantity,
                    ref_type=ref_type,
                    ref_id=ledger_ref,
                )
            )
        await self.inventory_repo.commit()

    async def fulfil_order_lines(
        self,
        tenant_id: str | uuid.UUID,
        *,
        warehouse_id: uuid.UUID,
        order_id: uuid.UUID,
        lines: Sequence[SalesOrderLine],
        ref_type: str = "sale_order",
    ) -> None:
        """Fulfil every line of one order in a SINGLE transaction.

        Consumption is serialized per line (guarded ``qty_reserved`` update),
        so a replay or a second concurrent fulfil fails with 409 before any
        movement is written — the sales service re-probes first and never
        reaches this method for an already-fulfilled order.
        """
        tid = _as_uuid(tenant_id)
        ref_id = str(order_id)
        emitted: list[tuple[Product, Decimal, Decimal]] = []
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError("Fulfilment quantity must be positive")
            product = await self._require_product(line.product_id, tid)
            await self._require_warehouse(warehouse_id, tid)
            before = await self._current_on_hand(line.product_id, warehouse_id, tid)

            if not await self.inventory_repo.apply_consume_qty(
                line.product_id, warehouse_id, line.quantity, tid
            ):
                raise InsufficientStockError()

            await self.inventory_repo.add_movement(
                StockMovement(
                    tenant_id=tid,
                    product_id=line.product_id,
                    warehouse_id=warehouse_id,
                    movement_type=StockMovementType.RELEASE,
                    qty=-line.quantity,
                    ref_type=ref_type,
                    ref_id=_step_ref(ref_id, _STEP_RELEASE),
                )
            )
            await self.inventory_repo.add_movement(
                StockMovement(
                    tenant_id=tid,
                    product_id=line.product_id,
                    warehouse_id=warehouse_id,
                    movement_type=StockMovementType.ISSUE,
                    qty=-line.quantity,
                    ref_type=ref_type,
                    ref_id=_step_ref(ref_id, _STEP_ISSUE),
                )
            )
            emitted.append((product, before, line.quantity))

        await self.inventory_repo.commit()

        for product, before, qty in emitted:
            await self._emit_level_changed(
                tenant_id=tid,
                product=product,
                warehouse_id=warehouse_id,
                before=before,
                after=before - qty,
            )

    # ------------------------------------------------------------------
    # Reads (thin forwards — the router owns response shaping)
    # ------------------------------------------------------------------

    async def list_products(
        self,
        tenant_id: str | uuid.UUID,
        *,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Product]:
        return await self.inventory_repo.list_products(
            _as_uuid(tenant_id),
            category=category,
            offset=offset,
            limit=limit,
        )

    async def count_products(
        self, tenant_id: str | uuid.UUID, *, category: str | None = None
    ) -> int:
        return await self.inventory_repo.count_products(_as_uuid(tenant_id), category=category)

    async def list_warehouses(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> Sequence[Warehouse]:
        return await self.inventory_repo.list_warehouses(
            _as_uuid(tenant_id), offset=offset, limit=limit
        )

    async def count_warehouses(self, tenant_id: str | uuid.UUID) -> int:
        return await self.inventory_repo.count_warehouses(_as_uuid(tenant_id))

    async def list_stock_levels(
        self,
        tenant_id: str | uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[StockLevel]:
        return await self.inventory_repo.list_stock_levels(
            _as_uuid(tenant_id),
            product_id=product_id,
            warehouse_id=warehouse_id,
            offset=offset,
            limit=limit,
        )

    async def count_stock_levels(
        self,
        tenant_id: str | uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
    ) -> int:
        return await self.inventory_repo.count_stock_levels(
            _as_uuid(tenant_id), product_id=product_id, warehouse_id=warehouse_id
        )

    async def list_movements(
        self,
        tenant_id: str | uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: StockMovementType | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[StockMovement]:
        return await self.inventory_repo.list_movements(
            _as_uuid(tenant_id),
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            offset=offset,
            limit=limit,
        )

    async def count_movements(
        self,
        tenant_id: str | uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        warehouse_id: uuid.UUID | None = None,
        movement_type: StockMovementType | None = None,
    ) -> int:
        return await self.inventory_repo.count_movements(
            _as_uuid(tenant_id),
            product_id=product_id,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
        )

    async def list_alerts(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> Sequence[tuple[StockLevel, Product]]:
        return await self.inventory_repo.list_low_stock(
            _as_uuid(tenant_id), offset=offset, limit=limit
        )

    async def count_alerts(self, tenant_id: str | uuid.UUID) -> int:
        return await self.inventory_repo.count_low_stock(_as_uuid(tenant_id))
