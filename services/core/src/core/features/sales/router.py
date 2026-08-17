"""Sales API routes — thin wrappers over :class:`SalesService`.

Authorization uses the ``erp.sales.*`` keys resolved at request time: ``read``
for reads, ``write`` for order creation/editing, ``approve`` for the money
moments (confirm / fulfil / cancel). Responses use the standard
``skyrict_common`` envelope; list endpoints are offset/limit paged.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import get_sales_service, require_permission
from core.core.permissions import ERP_SALES_APPROVE, ERP_SALES_READ, ERP_SALES_WRITE
from core.domain import entities as ent
from core.domain.value_objects import OrderStatus
from core.features.sales.schemas import (
    OrderCreateRequest,
    OrderLineRequest,
    OrderLineResponse,
    OrderResponse,
    OrderUpdateRequest,
)
from core.features.sales.service import OrderLineInput, SalesService
from skyrict_common.schemas import ListResponse, PaginationMeta, ResponseEnvelope

router = APIRouter(prefix="/sales/orders", tags=["sales"])

_require_sales_read = require_permission(ERP_SALES_READ)
_require_sales_write = require_permission(ERP_SALES_WRITE)
_require_sales_approve = require_permission(ERP_SALES_APPROVE)


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _order_out(order: ent.SalesOrder) -> OrderResponse:
    assert order.id is not None
    return OrderResponse(
        id=order.id,
        tenant_id=order.tenant_id,
        order_number=order.order_number,
        customer_id=order.customer_id,
        status=order.status,
        credit_check=order.credit_check,
        subtotal=order.subtotal.amount,
        discount=order.discount.amount,
        tax=order.tax.amount,
        total=order.total.amount,
        currency=order.subtotal.currency,
        confirmed_at=order.confirmed_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def _line_out(line: ent.SalesOrderLine) -> OrderLineResponse:
    assert line.id is not None
    assert line.order_id is not None
    return OrderLineResponse(
        id=line.id,
        tenant_id=line.tenant_id,
        order_id=line.order_id,
        product_id=line.product_id,
        product_name=line.product_name,
        sku=line.sku,
        quantity=line.quantity,
        unit_price=line.unit_price,
        discount=line.discount,
        tax=line.tax,
        line_total=line.line_total,
        created_at=line.created_at,
        updated_at=line.updated_at,
    )


@router.get("", response_model=ListResponse[OrderResponse])
async def list_orders(
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict[str, Any] = Depends(_require_sales_read),
    svc: SalesService = Depends(get_sales_service),
) -> ListResponse[OrderResponse]:
    orders = await svc.list_orders(
        tenant_id=_tenant_id(current_user),
        status=_parse_order_status(status),
        customer_id=customer_id,
        offset=offset,
        limit=limit,
    )
    total = await svc.count_orders(
        tenant_id=_tenant_id(current_user),
        status=_parse_order_status(status),
        customer_id=customer_id,
    )
    return ListResponse(
        data=[_order_out(order) for order in orders],
        meta=PaginationMeta.create(total=total, page=(offset // limit) + 1, page_size=limit),
    )


@router.post("", response_model=ResponseEnvelope[OrderResponse], status_code=201)
async def create_order(
    body: OrderCreateRequest,
    current_user: dict[str, Any] = Depends(_require_sales_write),
    svc: SalesService = Depends(get_sales_service),
) -> ResponseEnvelope[OrderResponse]:
    order = await svc.create_order(
        tenant_id=_tenant_id(current_user),
        customer_id=body.customer_id,
        lines=[_to_line_input(line) for line in body.lines],
    )
    return ResponseEnvelope(data=_order_out(order), message="Sales order created")


@router.get("/{order_id}", response_model=ResponseEnvelope[OrderResponse])
async def get_order(
    order_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_sales_read),
    svc: SalesService = Depends(get_sales_service),
) -> ResponseEnvelope[OrderResponse]:
    order = await svc.get_order(order_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_order_out(order))


@router.get("/{order_id}/lines", response_model=ListResponse[OrderLineResponse])
async def list_order_lines(
    order_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_sales_read),
    svc: SalesService = Depends(get_sales_service),
) -> ListResponse[OrderLineResponse]:
    lines = await svc.list_order_lines(order_id, tenant_id=_tenant_id(current_user))
    return ListResponse(
        data=[_line_out(line) for line in lines],
        meta=PaginationMeta.create(total=len(lines), page=1, page_size=len(lines) or 1),
    )


@router.patch("/{order_id}", response_model=ResponseEnvelope[OrderResponse])
async def update_order(
    order_id: uuid.UUID,
    body: OrderUpdateRequest,
    current_user: dict[str, Any] = Depends(_require_sales_write),
    svc: SalesService = Depends(get_sales_service),
) -> ResponseEnvelope[OrderResponse]:
    order = await svc.update_draft_order(
        order_id,
        tenant_id=_tenant_id(current_user),
        customer_id=body.customer_id,
        lines=[_to_line_input(line) for line in body.lines] if body.lines is not None else None,
    )
    return ResponseEnvelope(data=_order_out(order), message="Sales order updated")


@router.post("/{order_id}/confirm", response_model=ResponseEnvelope[OrderResponse])
async def confirm_order(
    order_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_sales_approve),
    svc: SalesService = Depends(get_sales_service),
) -> ResponseEnvelope[OrderResponse]:
    order = await svc.confirm_order(order_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_order_out(order), message="Sales order confirmed")


@router.post("/{order_id}/fulfil", response_model=ResponseEnvelope[OrderResponse])
async def fulfil_order(
    order_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_sales_approve),
    svc: SalesService = Depends(get_sales_service),
) -> ResponseEnvelope[OrderResponse]:
    order = await svc.fulfil_order(order_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_order_out(order), message="Sales order fulfilled")


@router.post("/{order_id}/cancel", response_model=ResponseEnvelope[OrderResponse])
async def cancel_order(
    order_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_sales_approve),
    svc: SalesService = Depends(get_sales_service),
) -> ResponseEnvelope[OrderResponse]:
    order = await svc.cancel_order(order_id, tenant_id=_tenant_id(current_user))
    return ResponseEnvelope(data=_order_out(order), message="Sales order cancelled")


def _parse_order_status(value: str | None) -> OrderStatus | None:
    if value is None:
        return None
    return OrderStatus(value)


def _to_line_input(line: OrderLineRequest) -> OrderLineInput:
    return OrderLineInput(product_id=line.product_id, quantity=line.quantity)
