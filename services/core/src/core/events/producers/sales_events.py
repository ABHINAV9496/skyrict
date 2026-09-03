"""Sales order event producers - structured domain events for the sales feature.

Follows the CRM/HR event pattern (docs/modules/sales-crm.md §2.5): each
``emit_*`` function builds the shared ``skyrict_events.BaseEvent`` envelope and
publishes it via ``apublish`` - buffered while a request transaction is open
and drained on the session's ``after_commit`` hook (core/db/session.py), so a
consumer can never observe order state that did not actually commit.

One event per transition (exactly the sales topics in §2.5): ``created`` on
draft insert, ``confirmed`` after the confirm transaction commits, ``fulfilled``
after fulfil commits, ``cancelled`` after cancel commits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events.producers import apublish
from skyrict_events.base import BaseEvent

if TYPE_CHECKING:
    import uuid


async def emit_order_created(
    *,
    order_id: uuid.UUID,
    order_number: str,
    tenant_id: uuid.UUID,
    customer_id: uuid.UUID,
    total: str,
    currency: str,
) -> None:
    """Emit ``sales.order.created`` (draft order inserted)."""
    event = BaseEvent(
        event_type="sales.order.created",
        tenant_id=str(tenant_id),
        metadata={
            "order_id": str(order_id),
            "order_number": order_number,
            "customer_id": str(customer_id),
            "total": total,
            "currency": currency,
        },
    )
    await apublish("sales.order.created", event, key=str(tenant_id))


async def emit_order_confirmed(
    *,
    order_id: uuid.UUID,
    order_number: str,
    tenant_id: uuid.UUID,
    credit_check: str,
) -> None:
    """Emit ``sales.order.confirmed`` (confirm transaction committed)."""
    event = BaseEvent(
        event_type="sales.order.confirmed",
        tenant_id=str(tenant_id),
        metadata={
            "order_id": str(order_id),
            "order_number": order_number,
            "credit_check": credit_check,
        },
    )
    await apublish("sales.order.confirmed", event, key=str(tenant_id))


async def emit_order_fulfilled(
    *,
    order_id: uuid.UUID,
    order_number: str,
    tenant_id: uuid.UUID,
    invoice_id: uuid.UUID,
) -> None:
    """Emit ``sales.order.fulfilled`` (fulfil transaction committed)."""
    event = BaseEvent(
        event_type="sales.order.fulfilled",
        tenant_id=str(tenant_id),
        metadata={
            "order_id": str(order_id),
            "order_number": order_number,
            "invoice_id": str(invoice_id),
        },
    )
    await apublish("sales.order.fulfilled", event, key=str(tenant_id))


async def emit_order_cancelled(
    *,
    order_id: uuid.UUID,
    order_number: str,
    tenant_id: uuid.UUID,
    released_stock: bool,
) -> None:
    """Emit ``sales.order.cancelled`` (cancel transaction committed).

    ``released_stock`` records whether the cancel also released reserved stock
    (true for a confirmed-but-unfulfilled order, false for a draft).
    """
    event = BaseEvent(
        event_type="sales.order.cancelled",
        tenant_id=str(tenant_id),
        metadata={
            "order_id": str(order_id),
            "order_number": order_number,
            "released_stock": released_stock,
        },
    )
    await apublish("sales.order.cancelled", event, key=str(tenant_id))
