"""Wave-4 schemas - payment-matching inbox (FIN-AUT-003 B7).

Request bodies feed :class:`~core.features.finance.payment_match.PaymentMatchService`;
response models validate the domain entities plus the live-read candidate list.
``InvoiceSuggestionResponse`` is a read-side object (never persisted) that pairs
an invoice's remaining balance with its deterministic match score, resolved at
inbox-read time so outstanding amounts stay current.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.domain.value_objects import PaymentIntentStatus

_PAYMENT_METHODS = ("bank_transfer", "cash", "card", "check", "wire")


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class PaymentIntentCreateRequest(BaseModel):
    amount: Decimal = Field(..., gt=0)
    paid_at: datetime
    method: str = Field(default="bank_transfer", min_length=1, max_length=32)
    reference: str | None = Field(default=None, max_length=120)
    source: str = Field(default="manual", min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=64)
    customer_id: uuid.UUID | None = None

    @field_validator("method")
    @classmethod
    def _known_method(cls, value: str) -> str:
        if value not in _PAYMENT_METHODS:
            raise ValueError(f"method must be one of {_PAYMENT_METHODS}")
        return value


class PaymentMatchAcceptRequest(BaseModel):
    invoice_id: uuid.UUID


class PaymentMatchBulkAcceptItem(BaseModel):
    intent_id: uuid.UUID
    invoice_id: uuid.UUID


class PaymentMatchBulkAcceptRequest(BaseModel):
    items: list[PaymentMatchBulkAcceptItem] = Field(..., min_length=0)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class InvoiceSuggestionResponse(BaseModel):
    invoice_id: uuid.UUID
    invoice_number: str
    customer_name: str | None = None
    outstanding: Decimal
    score: Decimal

    model_config = ConfigDict(from_attributes=True)


class PaymentIntentResponse(BaseModel):
    id: uuid.UUID
    reference: str | None = None
    amount: Decimal
    method: str
    paid_at: datetime
    source: str
    source_ref: str | None = None
    status: PaymentIntentStatus
    score: Decimal | None = None
    customer_name: str | None = None
    suggestions: list[InvoiceSuggestionResponse] = []
    suggested_invoice_id: uuid.UUID | None = None
    applied_invoice_id: uuid.UUID | None = None
    applied_payment_id: uuid.UUID | None = None
    applied_at: datetime | None = None
    applied_by: uuid.UUID | None = None
    dismissed_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaymentMatchBulkResult(BaseModel):
    intent_id: uuid.UUID
    ok: bool
    error: str | None = None
    payment_number: str | None = None


class PaymentMatchBulkAcceptResponse(BaseModel):
    results: list[PaymentMatchBulkResult]
