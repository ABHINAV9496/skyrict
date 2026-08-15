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
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from core.domain.entities import SalesOrder, SalesOrderLine
    from core.domain.value_objects import CreditCheckResult, OrderStatus


class SalesRepositoryPort(Protocol):
    """Persistence contract for sales orders and their lines."""

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

    async def list_order_lines(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[SalesOrderLine]: ...

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
