"""erp_budget_drafts - proposed budget drafts linked to L4 what-if scenarios (SKY-93).

A budget draft is a *planning artifact* — not a ledger transaction.  It lives
in the finance inbox so the finance team can review and approve proposed
workforce costs before they are committed to any journal entry.

``UNIQUE (tenant_id, source, source_ref)`` is the idempotency lock: one
proposed draft per scenario per tenant.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpBudgetDraftModel(Base):
    __tablename__ = "erp_budget_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending', 'approved')",
            name="ck_erp_budget_drafts_status",
        ),
        UniqueConstraint(
            "tenant_id",
            "source",
            "source_ref",
            name="uq_erp_budget_drafts_source_ref",
        ),
        Index("ix_erp_budget_drafts_tenant_status", "tenant_id", "status"),
        Index("ix_erp_budget_drafts_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    scenario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    scenario_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'draft'")
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    horizon: Mapped[int] = mapped_column(nullable=False)
    base_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    salary_total: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    benefit_total: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
