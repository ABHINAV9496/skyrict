"""Sales repository — DB operations for sales orders and their lines.

Concrete implementation of :class:`SalesRepositoryPort`. Orders are
tenant-scoped only (no owner/team columns — locked SKY-43 decision); every
query carries an explicit ``tenant_id`` filter as defense in depth under RLS.

- **Atomic document creation**: header + lines are flushed in one transaction;
  the repository stamps the generated header id onto every line (mirroring
  ``FinanceRepository.create_invoice``), so ``order_id`` is never client
  input.
- **Atomic state guards**: confirm/fulfil/cancel are conditional UPDATEs on
  the current status (``WHERE status = <expected>``). Exactly one concurrent
  caller wins (rowcount 1); a loser or a replay gets ``None`` back and the
  service short-circuits instead of double-executing side effects. The DB
  CHECK ``ck_erp_sales_orders_status_confirmed_at`` keeps ``confirmed_at``
  consistent with the status, so cancel clears it.
- The unique ``order_number`` violation is translated to a 409 ``ConflictError``
  (mirroring finance); FK/not-null violations surface as-is (programming
  errors must stay loud).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from core.domain.entities import SalesOrder, SalesOrderLine
from core.domain.value_objects import CreditCheckResult, Money, OrderStatus
from core.features.sales.models.order import ErpSalesOrderModel
from core.features.sales.models.order_line import ErpSalesOrderLineModel
from skyrict_common.exceptions import ConflictError

if TYPE_CHECKING:
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

_UNIQUE_VIOLATION_MESSAGES: dict[str, str] = {
    "uq_erp_sales_orders_tenant_number": "An order with this number already exists",
}
_DEFAULT_CONFLICT_MESSAGE = "The resource conflicts with existing data"

# Per-tenant document sequence claimed by this repository (wired at the
# composition root — features never import core.db), mirroring the HR
# repository's ``next_sequence``.
_ORDER_NUMBER_SEQUENCE = "sales_order"


def _conflict_or_reraise(exc: IntegrityError) -> None:
    """Translate a unique violation into a 409 ``ConflictError``, else re-raise.

    Only the known order-number UNIQUE constraint is translated; foreign-key /
    not-null violations are programming errors and must surface as 500s.
    """
    orig = getattr(exc, "orig", None)
    constraint = getattr(orig, "constraint_name", None)
    if constraint is None:
        diag = getattr(orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
    if constraint in _UNIQUE_VIOLATION_MESSAGES:
        raise ConflictError(_UNIQUE_VIOLATION_MESSAGES[constraint]) from exc
    sqlstate = getattr(orig, "sqlstate", None)
    if sqlstate == "23505":  # unique_violation with an unrecognized constraint
        raise ConflictError(_DEFAULT_CONFLICT_MESSAGE) from exc
    raise exc


def _order_to_orm(order: SalesOrder) -> ErpSalesOrderModel:
    kwargs: dict[str, object] = {
        "tenant_id": order.tenant_id,
        "order_number": order.order_number,
        "customer_id": order.customer_id,
        "status": order.status,
        "credit_check": order.credit_check,
        "subtotal": order.subtotal.amount,
        "discount": order.discount.amount,
        "tax": order.tax.amount,
        "total": order.total.amount,
        "currency_code": order.subtotal.currency,
        "confirmed_at": order.confirmed_at,
    }
    if order.id is not None:
        kwargs["id"] = order.id
    return ErpSalesOrderModel(**kwargs)


def _order_from_orm(model: ErpSalesOrderModel) -> SalesOrder:
    currency = model.currency_code
    return SalesOrder(
        id=model.id,
        tenant_id=model.tenant_id,
        order_number=model.order_number,
        customer_id=model.customer_id,
        status=model.status,
        credit_check=model.credit_check,
        subtotal=Money(model.subtotal, currency),
        discount=Money(model.discount, currency),
        tax=Money(model.tax, currency),
        total=Money(model.total, currency),
        confirmed_at=model.confirmed_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _line_to_orm(line: SalesOrderLine, *, order_id: uuid.UUID) -> ErpSalesOrderLineModel:
    return ErpSalesOrderLineModel(
        tenant_id=line.tenant_id,
        order_id=order_id,
        product_id=line.product_id,
        product_name=line.product_name,
        sku=line.sku,
        quantity=line.quantity,
        unit_price=line.unit_price,
        discount=line.discount,
        tax=line.tax,
        line_total=line.line_total,
    )


def _line_from_orm(model: ErpSalesOrderLineModel) -> SalesOrderLine:
    return SalesOrderLine(
        id=model.id,
        tenant_id=model.tenant_id,
        order_id=model.order_id,
        product_id=model.product_id,
        product_name=model.product_name,
        sku=model.sku,
        quantity=model.quantity,
        unit_price=model.unit_price,
        discount=model.discount,
        tax=model.tax,
        line_total=model.line_total,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SalesRepository:
    """Concrete SQLAlchemy implementation of :class:`SalesRepositoryPort`."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        next_sequence: Callable[[uuid.UUID, str], Awaitable[int]] | None = None,
    ) -> None:
        self.session = session
        self._next_sequence = next_sequence

    async def next_order_sequence(self, tenant_id: uuid.UUID) -> int:
        """Claim the next order-number sequence value (entity ``sales_order``).

        Race-safe and never reused (row-locking counter); the service formats
        the value into ``SO-{year}-{seq:05d}``.
        """
        if self._next_sequence is None:
            raise RuntimeError("SalesRepository was not wired with a sequence callable")
        return await self._next_sequence(tenant_id, _ORDER_NUMBER_SEQUENCE)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def create_order(self, order: SalesOrder, lines: Sequence[SalesOrderLine]) -> SalesOrder:
        model = _order_to_orm(order)
        self.session.add(model)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            _conflict_or_reraise(exc)

        line_models = [_line_to_orm(line, order_id=model.id) for line in lines]
        self.session.add_all(line_models)
        await self.session.flush()
        await self.session.refresh(model)
        return _order_from_orm(model)

    async def get_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder | None:
        stmt = select(ErpSalesOrderModel).where(
            ErpSalesOrderModel.tenant_id == tenant_id,
            ErpSalesOrderModel.id == order_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _order_from_orm(model) if model is not None else None

    async def get_order_by_number(
        self, order_number: str, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None:
        stmt = select(ErpSalesOrderModel).where(
            ErpSalesOrderModel.tenant_id == tenant_id,
            ErpSalesOrderModel.order_number == order_number,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _order_from_orm(model) if model is not None else None

    async def list_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        status: OrderStatus | None = None,
        customer_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[SalesOrder]:
        stmt = select(ErpSalesOrderModel).where(ErpSalesOrderModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ErpSalesOrderModel.status == status)
        if customer_id is not None:
            stmt = stmt.where(ErpSalesOrderModel.customer_id == customer_id)
        stmt = stmt.order_by(ErpSalesOrderModel.created_at.desc())
        result = await self.session.execute(stmt.offset(offset).limit(limit))
        return [_order_from_orm(model) for model in result.scalars().all()]

    async def count_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        status: OrderStatus | None = None,
        customer_id: uuid.UUID | None = None,
    ) -> int:
        """Total rows matching :meth:`list_orders` filters (pagination meta)."""
        stmt = (
            select(func.count())
            .select_from(ErpSalesOrderModel)
            .where(ErpSalesOrderModel.tenant_id == tenant_id)
        )
        if status is not None:
            stmt = stmt.where(ErpSalesOrderModel.status == status)
        if customer_id is not None:
            stmt = stmt.where(ErpSalesOrderModel.customer_id == customer_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def list_order_lines(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[SalesOrderLine]:
        stmt = select(ErpSalesOrderLineModel).where(
            ErpSalesOrderLineModel.tenant_id == tenant_id,
            ErpSalesOrderLineModel.order_id == order_id,
        )
        stmt = stmt.order_by(ErpSalesOrderLineModel.created_at.asc())
        result = await self.session.execute(stmt)
        return [_line_from_orm(model) for model in result.scalars().all()]

    async def update_draft_order(
        self,
        order_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None = None,
        lines: Sequence[SalesOrderLine] | None = None,
        totals: tuple[Money, Money, Money, Money] | None = None,
    ) -> SalesOrder | None:
        """PATCH a DRAFT order — change the customer and/or replace its lines.

        Atomic guard: the header UPDATE carries ``WHERE status = 'draft'``, so
        a confirmed/fulfilled/cancelled order is never mutated (rowcount 0 ->
        None, the service re-probes and replies accordingly). When neither
        field is provided the guard still runs and the current order returns
        (no-op PATCH). Lines are replaced wholesale (delete + insert in the
        same transaction) — never merged.

        ``totals`` is ``(subtotal, discount, tax, total)`` — the service's
        recomputed header money columns (clients never supply money); writing
        them in the SAME guarded UPDATE keeps the header consistent with the
        replaced lines atomically.
        """
        values: dict[str, object] = {
            "customer_id": (
                customer_id if customer_id is not None else ErpSalesOrderModel.customer_id
            )
        }
        if totals is not None:
            values["subtotal"] = totals[0].amount
            values["discount"] = totals[1].amount
            values["tax"] = totals[2].amount
            values["total"] = totals[3].amount
            values["currency_code"] = totals[0].currency
        stmt = (
            update(ErpSalesOrderModel)
            .where(
                ErpSalesOrderModel.tenant_id == tenant_id,
                ErpSalesOrderModel.id == order_id,
                ErpSalesOrderModel.status == OrderStatus.DRAFT,
            )
            .values(**values)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        if result.rowcount == 0:
            return None

        if lines is not None:
            await self.session.execute(
                delete(ErpSalesOrderLineModel).where(
                    ErpSalesOrderLineModel.tenant_id == tenant_id,
                    ErpSalesOrderLineModel.order_id == order_id,
                )
            )
            self.session.add_all([_line_to_orm(line, order_id=order_id) for line in lines])
        await self.session.flush()
        return await self.get_order(order_id, tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # State transitions (atomic guards)
    # ------------------------------------------------------------------

    async def confirm_order(
        self,
        order_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        confirmed_at: datetime,
        credit_check: CreditCheckResult,
    ) -> SalesOrder | None:
        """draft -> confirmed; returns the updated order, None when the guard loses."""
        stmt = (
            update(ErpSalesOrderModel)
            .where(
                ErpSalesOrderModel.tenant_id == tenant_id,
                ErpSalesOrderModel.id == order_id,
                ErpSalesOrderModel.status == OrderStatus.DRAFT,
            )
            .values(
                status=OrderStatus.CONFIRMED,
                confirmed_at=confirmed_at,
                credit_check=credit_check,
            )
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        if result.rowcount == 0:
            return None
        return await self.get_order(order_id, tenant_id=tenant_id)

    async def fulfil_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder | None:
        """confirmed -> fulfilled; returns the updated order, None when the guard loses."""
        stmt = (
            update(ErpSalesOrderModel)
            .where(
                ErpSalesOrderModel.tenant_id == tenant_id,
                ErpSalesOrderModel.id == order_id,
                ErpSalesOrderModel.status == OrderStatus.CONFIRMED,
            )
            .values(status=OrderStatus.FULFILLED)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        if result.rowcount == 0:
            return None
        return await self.get_order(order_id, tenant_id=tenant_id)

    async def cancel_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder | None:
        """draft|confirmed -> cancelled; returns the updated order, None when the guard loses.

        ``confirmed_at`` is cleared because the DB CHECK ties it to
        ``confirmed``/``fulfilled`` — a cancelled order must not carry it.
        """
        stmt = (
            update(ErpSalesOrderModel)
            .where(
                ErpSalesOrderModel.tenant_id == tenant_id,
                ErpSalesOrderModel.id == order_id,
                ErpSalesOrderModel.status.in_([OrderStatus.DRAFT, OrderStatus.CONFIRMED]),
            )
            .values(status=OrderStatus.CANCELLED, confirmed_at=None)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        if result.rowcount == 0:
            return None
        return await self.get_order(order_id, tenant_id=tenant_id)

    async def mark_credit_check_failed(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> SalesOrder | None:
        """Record a FAILED credit check on a draft order (informational).

        The order STAYS in draft — the DB has no opinion on the check result;
        the service re-runs the check on every confirm attempt, so raising the
        customer's limit later makes the same order confirmable.
        """
        stmt = (
            update(ErpSalesOrderModel)
            .where(
                ErpSalesOrderModel.tenant_id == tenant_id,
                ErpSalesOrderModel.id == order_id,
                ErpSalesOrderModel.status == OrderStatus.DRAFT,
            )
            .values(credit_check=CreditCheckResult.FAILED)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        if result.rowcount == 0:
            return None
        return await self.get_order(order_id, tenant_id=tenant_id)

    async def commit(self) -> None:
        """Commit the current transaction — the service owns the transaction lifecycle."""
        await self.session.commit()
