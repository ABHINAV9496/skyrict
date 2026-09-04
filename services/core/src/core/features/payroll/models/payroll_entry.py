"""erp_payroll_entries - one immutable result row per (run, employee).

A payroll computation snapshot: once a run is computed, every entry is frozen.
IMMUTABLE RECORD: no ``updated_at``, no update/delete endpoints in later
service tickets. ``adjustments`` is free-form JSONB (bonus/other deductions),
unstructured on purpose for now (spec §3.2). The one-way reference to
``erp_employees`` is the single sanctioned cross-feature model dependency.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class PayrollEntryModel(Base):
    """An immutable per-employee result row inside a payroll run."""

    __tablename__ = "erp_payroll_entries"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "employee_id", name="uq_erp_payroll_entries_run_employee"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["erp_payroll_runs.tenant_id", "erp_payroll_runs.id"],
            name="fk_erp_payroll_entries_run",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_payroll_entries_employee",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    base_salary: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    pay_days: Mapped[int] = mapped_column(Integer, nullable=False)
    gross: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    deductions: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    adjustments: Mapped[dict[str, object] | None] = mapped_column(postgresql.JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
