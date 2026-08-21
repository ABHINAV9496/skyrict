"""Sales service — sales orders and their lifecycle (CRM-BE-002 / sales-crm.md).

The service owns the business rules; the repository persists. Rules
implemented here (docs/modules/sales-crm.md §3, §4):

- **Server-side money**: every write recomputes line totals and the header
  (``subtotal - discount + tax``) from persisted line snapshots — clients
  never supply money columns.
- **Line snapshots**: ``product_name`` / ``sku`` / ``unit_price`` are copied
  from the product catalog at write time so history stays stable.
- **Order numbering**: ``SO-{year}-{seq:05d}``, strictly per-tenant sequential
  via the injected sequence callable (row-locking counter — race-safe).
- **State machine**: ``draft -> confirmed -> fulfilled`` (``cancelled``
  terminal from draft or confirmed). Each transition is an atomic guard in the
  repository; exactly one concurrent caller wins.
- **Idempotency (spec §10.2)**: confirm/fulfil/cancel re-probe first and
  short-circuit replays (a confirmed confirm returns the confirmed order); the
  UNIQUE ledger refs and the finance ``(source, source_ref)`` lock back the
  probe against races.
- **Credit check on confirm**: a customer with no limit passes; an exceeded
  limit keeps the order in ``draft`` with ``credit_check = failed`` and raises
  ``CreditLimitExceededError`` (422). The check re-runs on the next confirm
  attempt, so raising the limit later makes the same order confirmable.
- **Atomicity with stock**: the sales state guard and the stock reservation /
  release / fulfilment ride ONE request transaction and commit together inside
  the stock port's single commit. A stock failure (e.g. insufficient) rolls
  the state change back and leaves the order confirmable for a retry.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from core.audit_events import (
    SALES_ORDER_CANCELLED,
    SALES_ORDER_CONFIRMED,
    SALES_ORDER_CREATED,
    SALES_ORDER_FULFILLED,
    SALES_ORDER_UPDATED,
)
from core.core.exceptions import CreditLimitExceededError, IllegalStateTransitionError
from core.core.tenant_context import TenantContext
from core.domain.entities import Customer, Product, SalesOrder, SalesOrderLine
from core.domain.value_objects import (
    CreditCheckResult,
    CrmEntityType,
    CrmTimelineEventType,
    Money,
    OrderStatus,
)
from core.events.producers.sales_events import (
    emit_order_cancelled,
    emit_order_confirmed,
    emit_order_created,
    emit_order_fulfilled,
)
from core.features.finance.ports import SalesOrderForInvoicing
from core.features.finance.ports import SalesOrderLine as FinanceOrderLine
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from core.features.audit.service import AuditService
    from core.features.crm.ports import CrmTimelinePort
    from core.features.finance.ports import InvoicePort, CogsPort
    from core.features.sales.ports import (
        CustomerPort,
        OrderStockPort,
        ProductSnapshotPort,
        SalesRepositoryPort,
        WarehouseResolverPort,
    )

_ORDER_NUMBER_PREFIX = "SO"
_MONEY_QUANTUM = Decimal("0.01")

# Sales order -> finance DTO: revenue account stays unset so finance resolves
# the tenant's standard Revenue account (code 4000).
_FINANCE_DUE_DAYS = 30


@dataclass(frozen=True)
class OrderLineInput:
    """One client-supplied order line — only the product and the quantity.

    ``unit_price`` and the snapshot fields come from the product catalog
    server-side (never trusted from clients); money columns are derived.
    """

    product_id: uuid.UUID
    quantity: Decimal


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM)


class SalesService:
    """Implements the sales order business rules over :class:`SalesRepositoryPort`."""

    def __init__(
        self,
        repository: SalesRepositoryPort,
        customers: CustomerPort,
        stock: OrderStockPort,
        products: ProductSnapshotPort,
        warehouses: WarehouseResolverPort,
        invoice: InvoicePort,
        audit: AuditService,
        timeline: CrmTimelinePort,
        cogs: CogsPort | None = None,
    ) -> None:
        self._repo = repository
        self._customers = customers
        self._stock = stock
        self._products = products
        self._warehouses = warehouses
        self._invoice = invoice
        self._audit_service = audit
        self._timeline = timeline
        self._cogs = cogs

    # ------------------------------------------------------------------
    # Draft lifecycle
    # ------------------------------------------------------------------

    async def create_order(
        self,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID,
        lines: Sequence[OrderLineInput],
    ) -> SalesOrder:
        """Create a DRAFT order — validates the customer and snapshots products."""
        customer = await self._require_customer(customer_id, tenant_id=tenant_id)
        if not customer.is_active:
            raise ValidationError(f"Customer {customer_id} is deactivated")

        line_entities, currency = await self._build_lines(lines, tenant_id=tenant_id)
        number = await self._next_order_number(tenant_id)
        totals = _totals(line_entities)
        order = SalesOrder(
            tenant_id=tenant_id,
            order_number=number,
            customer_id=customer_id,
            status=OrderStatus.DRAFT,
            credit_check=CreditCheckResult.PENDING,
            subtotal=Money(totals[0], currency),
            discount=Money(totals[1], currency),
            tax=Money(totals[2], currency),
            total=Money(totals[3], currency),
        )
        created = await self._repo.create_order(order, line_entities)
        assert created.id is not None
        await self._audit(
            tenant_id=tenant_id,
            action=SALES_ORDER_CREATED,
            target=f"sales_order:{created.id}",
            details={
                "order_number": created.order_number,
                "customer_id": str(customer_id),
                "total": str(created.total.amount),
                "currency": currency,
            },
        )
        await emit_order_created(
            order_id=created.id,
            order_number=created.order_number,
            tenant_id=tenant_id,
            customer_id=customer_id,
            total=str(created.total.amount),
            currency=currency,
        )
        await self._timeline.record_timeline_event(
            tenant_id=tenant_id,
            entity_type=CrmEntityType.CUSTOMER,
            entity_id=customer_id,
            event_type=CrmTimelineEventType.ORDER_CREATED,
            title=f"Order {created.order_number} created",
            actor_id=uuid.UUID(TenantContext.get_user_id())
            if TenantContext.get_user_id()
            else None,
            payload={
                "order_id": str(created.id),
                "order_number": created.order_number,
                "total": str(created.total.amount),
                "currency": currency,
            },
        )
        return created

    async def get_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder:
        order = await self._repo.get_order(order_id, tenant_id=tenant_id)
        if order is None:
            raise NotFoundError(f"Sales order {order_id} not found")
        return order

    async def list_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        status: OrderStatus | None = None,
        customer_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[SalesOrder]:
        return list(
            await self._repo.list_orders(
                tenant_id=tenant_id,
                status=status,
                customer_id=customer_id,
                offset=offset,
                limit=limit,
            )
        )

    async def count_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        status: OrderStatus | None = None,
        customer_id: uuid.UUID | None = None,
    ) -> int:
        """Total rows matching :meth:`list_orders` filters (pagination meta)."""
        return await self._repo.count_orders(
            tenant_id=tenant_id,
            status=status,
            customer_id=customer_id,
        )

    async def list_order_lines(
        self, order_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[SalesOrderLine]:
        await self.get_order(order_id, tenant_id=tenant_id)  # 404 when absent
        return list(await self._repo.list_order_lines(order_id, tenant_id=tenant_id))

    async def update_draft_order(
        self,
        order_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        customer_id: uuid.UUID | None = None,
        lines: Sequence[OrderLineInput] | None = None,
    ) -> SalesOrder:
        """PATCH a DRAFT order — swap the customer and/or replace the lines."""
        if customer_id is not None:
            customer = await self._require_customer(customer_id, tenant_id=tenant_id)
            if not customer.is_active:
                raise ValidationError(f"Customer {customer_id} is deactivated")

        line_entities: list[SalesOrderLine] | None = None
        totals: tuple[Money, Money, Money, Money] | None = None
        if lines is not None:
            line_entities, currency = await self._build_lines(lines, tenant_id=tenant_id)
            money = _totals(line_entities)
            totals = (
                Money(money[0], currency),
                Money(money[1], currency),
                Money(money[2], currency),
                Money(money[3], currency),
            )

        updated = await self._repo.update_draft_order(
            order_id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            lines=line_entities,
            totals=totals,
        )
        if updated is None:
            current = await self._repo.get_order(order_id, tenant_id=tenant_id)
            if current is None:
                raise NotFoundError(f"Sales order {order_id} not found")
            raise IllegalStateTransitionError(
                f"Cannot update an order in status '{current.status}'"
            )

        await self._audit(
            tenant_id=tenant_id,
            action=SALES_ORDER_UPDATED,
            target=f"sales_order:{order_id}",
            details={"customer_id": str(customer_id) if customer_id else None},
        )
        return updated

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    async def confirm_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder:
        """``draft -> confirmed``: credit check + reservation, one transaction.

        Replay-safe: an already-confirmed order returns as-is. A failed credit
        check keeps the order in draft (``credit_check = failed``) and raises
        ``CreditLimitExceededError``. Insufficient stock rolls everything back
        and leaves the order confirmable for a retry (409).
        """
        order = await self._repo.get_order(order_id, tenant_id=tenant_id)
        if order is None:
            raise NotFoundError(f"Sales order {order_id} not found")
        if order.status is OrderStatus.CONFIRMED:
            return order  # replay
        if order.status is not OrderStatus.DRAFT:
            raise IllegalStateTransitionError(f"Cannot confirm an order in status '{order.status}'")

        customer = await self._require_customer(order.customer_id, tenant_id=tenant_id)
        lines = list(await self._repo.list_order_lines(order_id, tenant_id=tenant_id))
        warehouse = await self._resolve_warehouse(tenant_id)

        passed = _credit_check_passed(customer, order.total)
        if not passed:
            # Persist the FAILED marker + audit row atomically, then refuse:
            # the order STAYS in draft so a later limit raise makes it
            # confirmable again.
            await self._repo.mark_credit_check_failed(order_id, tenant_id=tenant_id)
            await self._audit(
                tenant_id=tenant_id,
                action=SALES_ORDER_UPDATED,
                target=f"sales_order:{order_id}",
                details={"credit_check": CreditCheckResult.FAILED.value},
            )
            await self._repo.commit()
            raise CreditLimitExceededError()

        confirmed = await self._repo.confirm_order(
            order_id,
            tenant_id=tenant_id,
            confirmed_at=datetime.now(UTC),
            credit_check=CreditCheckResult.PASSED,
        )
        if confirmed is None:
            # Lost the draft->confirmed guard: re-probe for a replay outcome.
            current = await self._repo.get_order(order_id, tenant_id=tenant_id)
            if current is not None and current.status is OrderStatus.CONFIRMED:
                return current
            raise IllegalStateTransitionError("Order was already transitioning")
        assert confirmed.id is not None
        await self._audit(
            tenant_id=tenant_id,
            action=SALES_ORDER_CONFIRMED,
            target=f"sales_order:{order_id}",
            details={
                "order_number": confirmed.order_number,
                "credit_check": CreditCheckResult.PASSED.value,
            },
        )
        await emit_order_confirmed(
            order_id=order_id,
            order_number=confirmed.order_number,
            tenant_id=tenant_id,
            credit_check=CreditCheckResult.PASSED.value,
        )
        await self._stock.reserve_order(
            tenant_id=tenant_id,
            warehouse_id=warehouse,
            order_id=order_id,
            lines=lines,
        )
        return confirmed

    async def fulfil_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder:
        """``confirmed -> fulfilled``: invoice + stock consumption, one transaction.

        Replay-safe: an already-fulfilled order returns as-is. The invoice is
        created idempotently by finance (``(source, source_ref)`` UNIQUE) and
        commits together with the state guard and the stock consumption.
        """
        order = await self._repo.get_order(order_id, tenant_id=tenant_id)
        if order is None:
            raise NotFoundError(f"Sales order {order_id} not found")
        if order.status is OrderStatus.FULFILLED:
            return order  # replay
        if order.status is not OrderStatus.CONFIRMED:
            raise IllegalStateTransitionError(f"Cannot fulfil an order in status '{order.status}'")

        lines = list(await self._repo.list_order_lines(order_id, tenant_id=tenant_id))
        warehouse = await self._resolve_warehouse(tenant_id)
        invoice = await self._invoice.create_from_order(
            SalesOrderForInvoicing(
                tenant_id=tenant_id,
                order_id=str(order_id),
                customer_id=order.customer_id,
                invoice_date=datetime.now(UTC).date(),
                due_date=(datetime.now(UTC).date() + timedelta(days=_FINANCE_DUE_DAYS)),
                lines=tuple(
                    FinanceOrderLine(
                        description=line.product_name,
                        account_id=None,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                    )
                    for line in lines
                ),
                currency=order.subtotal.currency,
            )
        )
        assert invoice.id is not None

        fulfilled = await self._repo.fulfil_order(order_id, tenant_id=tenant_id)
        if fulfilled is None:
            # Lost the confirmed->fulfilled guard: re-probe for a replay outcome.
            current = await self._repo.get_order(order_id, tenant_id=tenant_id)
            if current is not None and current.status is OrderStatus.FULFILLED:
                return current
            raise IllegalStateTransitionError("Order was already transitioning")
        assert fulfilled.id is not None
        await self._audit(
            tenant_id=tenant_id,
            action=SALES_ORDER_FULFILLED,
            target=f"sales_order:{order_id}",
            details={"order_number": fulfilled.order_number, "invoice_id": str(invoice.id)},
        )
        await emit_order_fulfilled(
            order_id=order_id,
            order_number=fulfilled.order_number,
            tenant_id=tenant_id,
            invoice_id=invoice.id,
        )
        cost_data = await self._stock.fulfil_order_lines(
            tenant_id=tenant_id,
            warehouse_id=warehouse,
            order_id=order_id,
            lines=lines,
        )
        if self._cogs is not None and cost_data:
            from core.features.finance.ports import CogsLine

            cogs_lines = [
                CogsLine(product_id=pid, quantity=qty, unit_cost=cost)
                for pid, qty, cost in cost_data
            ]
            await self._cogs.post_cogs_for_order(
                tenant_id=tenant_id,
                order_id=str(order_id),
                entry_date=datetime.now(UTC).date(),
                lines=cogs_lines,
            )
        return fulfilled

    async def cancel_order(self, order_id: uuid.UUID, *, tenant_id: uuid.UUID) -> SalesOrder:
        """``draft|confirmed -> cancelled``; a confirmed order releases stock.

        Replay-safe: an already-cancelled order returns as-is. A fulfilled
        order cannot be cancelled.
        """
        order = await self._repo.get_order(order_id, tenant_id=tenant_id)
        if order is None:
            raise NotFoundError(f"Sales order {order_id} not found")
        if order.status is OrderStatus.CANCELLED:
            return order  # replay
        if order.status is not OrderStatus.DRAFT and order.status is not OrderStatus.CONFIRMED:
            raise IllegalStateTransitionError(f"Cannot cancel an order in status '{order.status}'")

        released_stock = order.status is OrderStatus.CONFIRMED
        cancelled = await self._repo.cancel_order(order_id, tenant_id=tenant_id)
        if cancelled is None:
            current = await self._repo.get_order(order_id, tenant_id=tenant_id)
            if current is not None and current.status is OrderStatus.CANCELLED:
                return current  # replay — the winning caller did the side effects
            raise IllegalStateTransitionError("Order was already transitioning")
        assert cancelled.id is not None

        await self._audit(
            tenant_id=tenant_id,
            action=SALES_ORDER_CANCELLED,
            target=f"sales_order:{order_id}",
            details={"order_number": cancelled.order_number, "released_stock": released_stock},
        )
        await emit_order_cancelled(
            order_id=order_id,
            order_number=cancelled.order_number,
            tenant_id=tenant_id,
            released_stock=released_stock,
        )
        if released_stock:
            lines = list(await self._repo.list_order_lines(order_id, tenant_id=tenant_id))
            warehouse = await self._resolve_warehouse(tenant_id)
            await self._stock.release_order(
                tenant_id=tenant_id,
                warehouse_id=warehouse,
                order_id=order_id,
                lines=lines,
            )
        else:
            await self._repo.commit()
        return cancelled

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _require_customer(self, customer_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Customer:
        customer = await self._customers.get_customer(customer_id, tenant_id=tenant_id)
        if customer is None:
            raise NotFoundError(f"Customer {customer_id} not found")
        return customer

    async def _build_lines(
        self, lines: Sequence[OrderLineInput], *, tenant_id: uuid.UUID
    ) -> tuple[list[SalesOrderLine], str]:
        """Validate client lines and build snapshotted order lines.

        ``unit_price`` comes from the product catalog (``sell_price``) — the
        client only supplies ``product_id`` and ``quantity``.
        """
        if not lines:
            raise ValidationError("An order needs at least one line")
        built: list[SalesOrderLine] = []
        currency: str | None = None
        for line in lines:
            if line.quantity <= 0:
                raise ValidationError("Line quantity must be positive")

            product = await self._require_product(line.product_id, tenant_id=tenant_id)
            if not product.is_active:
                raise ValidationError(f"Product {line.product_id} is deactivated")
            if currency is None:
                currency = product.sell_price.currency
            elif product.sell_price.currency != currency:
                raise ValidationError("All order lines must share one currency")
            assert product.id is not None
            built.append(
                SalesOrderLine(
                    tenant_id=tenant_id,
                    product_id=product.id,
                    product_name=product.name,
                    sku=product.sku,
                    quantity=line.quantity,
                    unit_price=product.sell_price.amount,
                    discount=Decimal("0"),
                    tax=Decimal("0"),
                    line_total=_quantize(line.quantity * product.sell_price.amount),
                )
            )
        assert currency is not None
        return built, currency

    async def _require_product(self, product_id: uuid.UUID, *, tenant_id: uuid.UUID) -> Product:
        product = await self._products.get_product(product_id, tenant_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found")
        return product

    async def _resolve_warehouse(self, tenant_id: uuid.UUID) -> uuid.UUID:
        """Deterministic stock-side warehouse: the first active warehouse."""
        warehouses = await self._warehouses.list_warehouses(tenant_id)
        if not warehouses:
            raise ValidationError("No active warehouse available to process the order")
        warehouse_id = warehouses[0].id
        if warehouse_id is None:
            raise ValidationError("Active warehouse has no id")
        return warehouse_id

    async def _next_order_number(self, tenant_id: uuid.UUID) -> str:
        seq = await self._repo.next_order_sequence(tenant_id)
        return f"{_ORDER_NUMBER_PREFIX}-{datetime.now(UTC).year}-{seq:05d}"

    async def _audit(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        target: str,
        details: dict[str, Any] | None,
    ) -> None:
        await self._audit_service.log(
            action=action,
            target=target,
            user_id=TenantContext.get_user_id(),
            tenant_id=str(tenant_id),
            details=details,
        )


def _totals(lines: list[SalesOrderLine]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Recompute (subtotal, discount, tax, total) from the line projections.

    Total is derived — never trusted from clients; every money column is
    quantized to the ERP money quantum (2 dp).
    """
    subtotal = sum((line.line_total for line in lines), Decimal("0"))
    discount = sum((line.discount for line in lines), Decimal("0"))
    tax = sum((line.tax for line in lines), Decimal("0"))
    total = subtotal - discount + tax
    return (
        _quantize(subtotal),
        _quantize(discount),
        _quantize(tax),
        _quantize(total),
    )


def _credit_check_passed(customer: Customer, total: Money) -> bool:
    """A customer with no limit passes; otherwise compare against the limit."""
    if customer.credit_limit is None:
        return True
    return customer.credit_limit.amount >= total.amount
