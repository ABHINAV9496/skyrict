"""erp_invoices — accounts-receivable documents (bills to customers).

``status`` drives revenue recognition: revenue is only recognized at
``approved`` (accrual basis), never at issue or payment. The transition
timestamps record when each state change happened. ``UNIQUE
(tenant_id, invoice_number)`` guarantees every bill has a distinct number.
``customer_id`` is a plain UUID reference to CRM (CRM owns customers); no FK.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import InvoiceStatus
from core.models.base import Base


class ErpInvoiceModel(Base):
    __tablename__ = "erp_invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "invoice_number", name="uq_erp_invoices_tenant_number"),
        CheckConstraint("due_date >= invoice_date", name="ck_erp_invoices_due_date_range"),
        CheckConstraint("total >= 0", name="ck_erp_invoices_total_non_negative"),
        Index("ix_erp_invoices_tenant_status", "tenant_id", "status"),
        Index("ix_erp_invoices_tenant_customer", "tenant_id", "customer_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(
            InvoiceStatus,
            name="erp_invoice_status",
            create_type=False,
            values_callable=lambda cls: [member.value for member in cls],
        ),
        nullable=False,
        server_default=text("'draft'"),
    )
    total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, server_default=text("0"))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
