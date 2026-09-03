"""Sales API schemas - request bodies and response models (CRM-BE-002).

Request models validate client input; response models validate domain entities
(``from_attributes``) so the router stays a thin translation layer. Money
fields live on the order header as ``amount`` + ``currency`` (the currency is
derived server-side from the product catalog and never trusted from clients).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from core.domain.value_objects import CreditCheckResult, OrderStatus

# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


class OrderLineRequest(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(..., gt=0)


class OrderCreateRequest(BaseModel):
    customer_id: uuid.UUID
    lines: list[OrderLineRequest] = Field(..., min_length=1)


class OrderUpdateRequest(BaseModel):
    customer_id: uuid.UUID | None = None
    lines: list[OrderLineRequest] | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    status: OrderStatus
    credit_check: CreditCheckResult
    subtotal: Decimal
    discount: Decimal
    tax: Decimal
    total: Decimal
    currency: str
    confirmed_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class OrderLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    order_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    quantity: Decimal
    unit_price: Decimal
    discount: Decimal
    tax: Decimal
    line_total: Decimal
    created_at: datetime | None
    updated_at: datetime | None
