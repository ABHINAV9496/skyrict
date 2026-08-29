"""SQLAlchemy ORM models for the payroll automation batch engine (HR-AUT-001).

Migration 0026 is the source of truth for the schema; these models must stay in
lockstep with it (composite ``(tenant_id, id)`` PKs, string statuses with check
constraints, RLS enabled via ``tenant_isolation_*`` policies).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import text

from core.models.base import Base, TimestampMixin


class PayrollBatchRunModel(Base, TimestampMixin):
    """A queued/processing/finished payroll automation batch run."""

    __tablename__ = "ai_payroll_batch_runs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    claimed_by: Mapped[str | None] = mapped_column(String(64))
    preflight: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    totals: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'failed', 'aborted')",
            name="ck_ai_payroll_batch_runs_status",
        ),
        UniqueConstraint(
            "tenant_id",
            "source",
            "source_ref",
            name="uq_ai_payroll_batch_runs_source",
        ),
        Index("ix_ai_payroll_batch_runs_claim", "status", "created_at"),
    )


class PayrollBatchItemModel(Base, TimestampMixin):
    """One per-employee work item within a batch run."""

    __tablename__ = "ai_payroll_batch_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_text: Mapped[str | None] = mapped_column(String(1024))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "batch_id"],
            ["ai_payroll_batch_runs.tenant_id", "ai_payroll_batch_runs.id"],
            name="fk_ai_payroll_batch_items_batch",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_payroll_batch_items_employee",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_ai_payroll_batch_items_status",
        ),
        UniqueConstraint("batch_id", "employee_id", name="uq_ai_payroll_batch_items_emp"),
        Index("ix_ai_payroll_batch_items_proc", "tenant_id", "batch_id", "status"),
    )


__all__ = ["PayrollBatchItemModel", "PayrollBatchRunModel"]
