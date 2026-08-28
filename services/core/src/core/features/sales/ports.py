"""Sales ports — persistence contract for the sales feature.

Declares what the repository must offer so the future service depends on a
Protocol (hexagonal "ports") rather than the concrete SQLAlchemy
implementation. The repository lives in the same feature package, so there is
no import-linter violation.

Orders have no owner/team columns (locked SKY-43 decision) — they are
tenant-scoped only, and RLS bounds the tenant. The side-effecting state
transitions (confirm/fulfil/cancel) are atomic state guards in the repository
(conditional UPDATE on the current status); exactly one concurrent caller
wins, and a replay that loses the guard gets ``None`` back.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from core.domain.entities import Customer, Product, SalesOrder, SalesOrderLine, Warehouse
    from core.domain.value_objects import CreditCheckResult, Money, OrderStatus


class SalesRepositoryPort(Protocol):
    """Persistence contract for sales orders and their lines."""

    # --- Document sequences (wired at the composition root) ---
    async def next_order_sequence(self, tenant_id: uuid.UUID) -> int: ...

    # --- Orders (header + lines, one transaction) ---
    async def create_order(
        self, order: SalesOrder, lines: Sequence[SalesOrderLine]
    ) -> SalesOrder: ...

    async def get_order(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None: ...

    async def get_order_by_number(
        self, order_number: str, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None: ...

    async def list_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        status: OrderStatus | None = None,
        customer_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[SalesOrder]: ...

    async def count_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        status: OrderStatus | None = None,
        customer_id: uuid.UUID | None = None,
    ) -> int: ...

    async def list_order_lines(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[SalesOrderLine]: ...

    async def update_draft_order(
        self,
        order_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None = None,
        lines: Sequence[SalesOrderLine] | None = None,
        totals: tuple[Money, Money, Money, Money] | None = None,
    ) -> SalesOrder | None: ...

    # --- State transitions (atomic guards — return None when the guard loses) ---
    async def confirm_order(
        self,
        order_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        confirmed_at: datetime,
        credit_check: CreditCheckResult,
    ) -> SalesOrder | None: ...

    async def fulfil_order(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None: ...

    async def cancel_order(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None: ...

    async def mark_credit_check_failed(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None: ...

    async def commit(self) -> None: ...


# ---------------------------------------------------------------------------
# Cross-module ports (seams the sales service calls — no feature imports)
# ---------------------------------------------------------------------------


class CustomerPort(Protocol):
    """CRM customer lookup — implemented structurally by the CRM repository."""

    async def get_customer(
        self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Customer | None: ...


class ProductSnapshotPort(Protocol):
    """Inventory product lookup for order-line snapshots (name/sku/price)."""

    async def get_product(self, product_id: uuid.UUID, tenant_id: uuid.UUID) -> Product | None: ...


class WarehouseResolverPort(Protocol):
    """Inventory warehouse lookup for deterministic stock-side resolution."""

    async def list_warehouses(
        self,
        tenant_id: uuid.UUID,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 20,
    ) -> Sequence[Warehouse]: ...


class OrderStockPort(Protocol):
    """Whole-order stock reservation lifecycle — implemented structurally by
    ``InventoryService``.

    Each method applies the SAME per-line semantics as inventory's per-line
    reservation API but defers the single commit to the end, so an order's
    reservation / release / fulfilment is all-or-nothing AND that one commit
    also persists the sales-order state guard that ran just before in the same
    request transaction.
    """

    async def reserve_order(
        self,
        tenant_id: str | uuid.UUID,
        *,
        warehouse_id: uuid.UUID,
        order_id: uuid.UUID,
        lines: Sequence[SalesOrderLine],
        ref_type: str = "sale_order",
    ) -> None: ...

    async def release_order(
        self,
        tenant_id: str | uuid.UUID,
        *,
        warehouse_id: uuid.UUID,
        order_id: uuid.UUID,
        lines: Sequence[SalesOrderLine],
        ref_type: str = "sale_order",
    ) -> None: ...

    async def fulfil_order_lines(
        self,
        tenant_id: str | uuid.UUID,
        *,
        warehouse_id: uuid.UUID,
        order_id: uuid.UUID,
        lines: Sequence[SalesOrderLine],
        ref_type: str = "sale_order",
    ) -> list[tuple[uuid.UUID, Decimal, Decimal]]: ...
