"""erp_invoice_lines - the line items of an invoice.

CASCADE on the invoice FK because a line has no life without its invoice;
RESTRICT on the account FK because history is eternal (accounts are
deactivated, never deleted). ``amount = quantity * unit_price`` is verified
by the database itself (NUMERIC arithmetic is exact), so a stored line always
matches its numbers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpInvoiceLineModel(Base):
    __tablename__ = "erp_invoice_lines"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["erp_invoices.tenant_id", "erp_invoices.id"],
            ondelete="CASCADE",
            name="fk_erp_invoice_lines_invoice",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["erp_chart_of_accounts.tenant_id", "erp_chart_of_accounts.id"],
            ondelete="RESTRICT",
            name="fk_erp_invoice_lines_account",
        ),
        CheckConstraint("quantity > 0", name="ck_erp_invoice_lines_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_erp_invoice_lines_unit_price_non_negative"),
        CheckConstraint("amount >= 0", name="ck_erp_invoice_lines_amount_non_negative"),
        CheckConstraint(
            "amount = quantity * unit_price", name="ck_erp_invoice_lines_amount_consistent"
        ),
        Index("ix_erp_invoice_lines_tenant_invoice", "tenant_id", "invoice_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
