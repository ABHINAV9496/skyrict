"""erp_payroll_runs - a monthly payroll run covering a whole tenant period.

A run is NOT employee-scoped - it covers every active employee for a period.
``total_gross``/``total_net`` are NULLABLE on purpose: NULL means "not yet
computed", which must stay distinct from a genuine zero-dollar run. The
partial unique index ``uq_erp_payroll_runs_period_active`` (same tenant +
overlapping period, WHERE status <> 'void') lives in migration 0005, not here.

``je_bridge_status`` tracks the payroll→Finance accrual journal-entry bridge
(HR-AUT-001, Commit 4): ``none`` / ``pending`` / ``draft``. It is a String
column with a CHECK constraint (not a native enum) so FIN-AI-001 can extend
it without a migration.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class PayrollRunStatus(enum.StrEnum):
    """Native enum ``erp_payroll_run_status`` (created by migration 0005)."""

    DRAFT = "draft"
    COMPUTED = "computed"
    APPROVED = "approved"
    PAID = "paid"
    VOID = "void"


class PayrollRounding(enum.StrEnum):
    """Native enum ``erp_payroll_rounding`` (created by migration 0005)."""

    NEAREST = "nearest"
    UP = "up"
    DOWN = "down"


class PayrollRunModel(Base):
    """A payroll run covering one tenant and one monthly period."""

    __tablename__ = "erp_payroll_runs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "run_code", name="uq_erp_payroll_runs_tenant_code"),
        CheckConstraint(
            "je_bridge_status IN ('none', 'pending', 'draft')",
            name="ck_erp_payroll_runs_je_bridge_status",
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
    run_code: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PayrollRunStatus] = mapped_column(
        Enum(
            PayrollRunStatus,
            name="erp_payroll_run_status",
            create_type=False,
            values_callable=lambda cls: [m.value for m in cls],
        ),
        nullable=False,
        server_default=text("'draft'"),
    )
    total_gross: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_net: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # Approver/executor user UUIDs - plain UUIDs, no FK (identity service).
    computed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Employees excluded at compute time, with the reason (gap #6).
    skipped_employees: Mapped[list[dict[str, str]] | None] = mapped_column(JSONB, nullable=True)
    # Payroll→Finance accrual JE bridge state — none/pending/draft (Commit 4).
    je_bridge_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'none'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
