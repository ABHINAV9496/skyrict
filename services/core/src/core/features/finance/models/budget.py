"""erp_budgets - fiscal-year operating budgets (FIN-AUT-004, SKY-85 B21).

The plan header: ``draft`` (editable) -> ``active`` (frozen, variance-read
target) -> ``closed`` (terminal). Lines live in ``erp_budget_lines`` and
reference ``account_code`` strings (resolved at variance-read time), so the
plan stays readable across account renames. Amounts are Decimal/NUMERIC(20,2)
matching the rest of the finance ledger.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpBudgetModel(Base):
    __tablename__ = "erp_budgets"
    __table_args__ = (
        Index("ix_erp_budgets_tenant_status", "tenant_id", "status"),
        Index("ix_erp_budgets_tenant_year", "tenant_id", "fiscal_year"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default=text("'USD'"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ErpBudgetLineModel(Base):
    __tablename__ = "erp_budget_lines"
    __table_args__ = (
        Index("ix_erp_budget_lines_tenant_budget", "tenant_id", "budget_id"),
        UniqueConstraint(
            "tenant_id", "budget_id", "account_code", name="uq_erp_budget_lines_tenant_budget_code"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_code: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
