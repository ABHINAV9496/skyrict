"""erp_payments - cash receipts applied to an invoice.

RESTRICT on the invoice FK: payments are history and a paid invoice is never
deleted. ``UNIQUE (tenant_id, source, source_ref)`` is the second idempotency
lock (a replayed apply_payment cannot double-book); ``payment_number`` mirrors
the invoice numbering rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import PaymentStatus
from core.models.base import Base


class ErpPaymentModel(Base):
    __tablename__ = "erp_payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["erp_invoices.tenant_id", "erp_invoices.id"],
            ondelete="RESTRICT",
            name="fk_erp_payments_invoice",
        ),
        UniqueConstraint("tenant_id", "payment_number", name="uq_erp_payments_tenant_number"),
        UniqueConstraint("tenant_id", "source", "source_ref", name="uq_erp_payments_source_ref"),
        CheckConstraint("amount > 0", name="ck_erp_payments_amount_positive"),
        Index("ix_erp_payments_tenant_invoice", "tenant_id", "invoice_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    payment_number: Mapped[str] = mapped_column(String(32), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            name="erp_payment_status",
            create_type=False,
            values_callable=lambda cls: [member.value for member in cls],
        ),
        nullable=False,
        server_default=text("'applied'"),
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
