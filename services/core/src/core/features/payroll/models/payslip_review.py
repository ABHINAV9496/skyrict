"""erp_payslip_reviews — versioned payslip review with approval lifecycle.

Each row is one employee's computed payslip in a specific payroll run, with an
approval lifecycle (``draft`` → ``approved`` | ``rejected``). Re-approval after
correction creates a new version row (unique on tenant + run + employee +
version), enabling the notification delivery-gate to fire only once per
approved version.

IMMUTABLE once ``approved`` or ``rejected``: the service layer gates all
transitions; approved rows are never overwritten or deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from core.models.base import Base


class PayslipReviewModel(Base):
    """Versioned payslip review row — one per (run, employee, version)."""

    __tablename__ = "erp_payslip_reviews"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "employee_id",
            "version",
            name="uq_erp_payslip_reviews_run_employee_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["erp_payroll_runs.tenant_id", "erp_payroll_runs.id"],
            name="fk_erp_payslip_reviews_run",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_payslip_reviews_employee",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('draft', 'approved', 'rejected')",
            name="ck_erp_payslip_reviews_status",
        ),
        Index(
            "ix_erp_payslip_reviews_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_erp_payslip_reviews_tenant_run",
            "tenant_id",
            "run_id",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_number: Mapped[str] = mapped_column(String(32), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(128), nullable=False)
    gross: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    deductions: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    rejected_reason: Mapped[str | None] = mapped_column(String(), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
