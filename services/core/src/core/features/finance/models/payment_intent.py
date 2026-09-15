"""erp_payment_intents - unmatched receipts in the payment-matching inbox (B7).

An intent is a cash receipt with no invoice attached yet (bank feed, manual
entry, or a document-extracted vendor reference from B23). The box is
configuration-lite: the deterministic ``score_match`` heuristic computes a
confidence at create time (stored for inbox sorting) and candidates are
recomputed live per read. Accepted intents become real ``erp_payments`` rows
via the existing ``apply_payment`` path - the intent only remembers which
payment it created so the 15-minute undo can delete exactly that row.

``(source, source_ref)`` with a partial unique index (``WHERE source_ref IS
NOT NULL``) is the idempotency stamp for bank-feed pushes, mirroring the
payments table's full uniqueness.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpPaymentIntentModel(Base):
    __tablename__ = "erp_payment_intents"
    __table_args__ = (Index("ix_erp_payment_intents_tenant_status", "tenant_id", "status"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    method: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'bank_transfer'")
    )
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'open'"))
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    suggested_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    applied_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    applied_payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
