"""erp_attendance_records — one attendance row per employee per work day.

``status`` is a REAL native enum (``erp_attendance_status``, created by
migration 0017). ``pay_impact`` is derived by the service from the status
(on_time -> full, late -> half, absent -> none) and CHECK-constrained in the
database — never trusted from clients. One record per
``(tenant_id, employee_id, work_date)``; corrections upsert the same day.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.core.constants import AttendanceStatus, PayImpact
from core.models.base import Base


class AttendanceRecordModel(Base):
    """A single day's attendance for one tenant employee."""

    __tablename__ = "erp_attendance_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_attendance_records_employee",
        ),
        {"comment": "One row per employee per work day; upserted in place."},
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
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(
            AttendanceStatus,
            name="erp_attendance_status",
            create_type=False,
            values_callable=lambda cls: [m.value for m in cls],
        ),
        nullable=False,
    )
    pay_impact: Mapped[PayImpact] = mapped_column(String(8), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
