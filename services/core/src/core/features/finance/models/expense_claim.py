"""erp_expense_claims - submitted employee expenses (FIN-AUT-004, SKY-85 B16).

A claim only becomes a row after policy evaluation allows it (hard blocks
409 before insert). ``source_ref`` mirrors journal templates so a replayed
submission stamp stays idempotent; ``status`` moves ``submitted -> approved``
or ``submitted -> rejected`` with a stored reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpExpenseClaimModel(Base):
    __tablename__ = "erp_expense_claims"
    __table_args__ = (
        Index("ix_erp_expense_claims_tenant_status", "tenant_id", "status"),
        UniqueConstraint("tenant_id", "source_ref", name="uq_erp_expense_claims_source_ref"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    advance_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'submitted'")
    )
    source_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
