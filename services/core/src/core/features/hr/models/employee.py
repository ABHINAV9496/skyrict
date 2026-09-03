"""erp_employees - the people records.

``employment_status`` is the single source of employment truth - there is
deliberately NO separate ``is_active`` flag. ``termination_date`` is required
when status is ``terminated`` (DB CHECK ``ck_erp_employees_termination_required``).

Cascade policy: ``tenant_id -> tenants`` is CASCADE; ``department_id`` and every
child FK elsewhere are NO ACTION, so an employee with any leave/payroll history
can never be hard-deleted - only moved to ``terminated``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class EmploymentStatus(enum.StrEnum):
    """Native enum ``erp_employment_status`` (created by migration 0005)."""

    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class EmployeeModel(Base):
    """A person employed within a tenant."""

    __tablename__ = "erp_employees"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_number", name="uq_erp_employees_tenant_number"),
        ForeignKeyConstraint(
            ["tenant_id", "department_id"],
            ["erp_departments.tenant_id", "erp_departments.id"],
            name="fk_erp_employees_department",
        ),
        CheckConstraint(
            "employment_status <> 'terminated' OR termination_date IS NOT NULL",
            name="ck_erp_employees_termination_required",
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
    employee_number: Mapped[str] = mapped_column(String(20), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Identity user link - plain UUID, no FK (identity lives in another service).
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    job_title: Mapped[str] = mapped_column(String(100), nullable=False)
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        Enum(
            EmploymentStatus,
            name="erp_employment_status",
            create_type=False,
            values_callable=lambda cls: [m.value for m in cls],
        ),
        nullable=False,
        server_default=text("'active'"),
    )
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
