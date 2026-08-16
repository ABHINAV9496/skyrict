"""erp_leave_movements — the immutable leave ledger.

Every balance-affecting event writes ONE row here; balances are recomputed
from this ledger (spec §3.2), never stored as a mutable counter. IMMUTABLE
RECORD: no ``updated_at``, no update/delete endpoints in later service
tickets. ``qty <> 0`` is enforced at the service layer, not by a DB CHECK.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class LeaveMovementModel(Base):
    """One immutable entry in the leave ledger for a single employee."""

    __tablename__ = "erp_leave_movements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_leave_movements_employee",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "leave_type"],
            ["erp_leave_types.tenant_id", "erp_leave_types.code"],
            name="fk_erp_leave_movements_leave_type",
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
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    leave_type: Mapped[str] = mapped_column(String(32), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    ref_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # The reference id: the leave_year for ``annual_accrual`` (a plain string,
    # e.g. "2025"), a leave request id for ``leave_request``, or an adjustment
    # id for ``manual_adjustment`` — mirrors the inventory ledger's String(64).
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
