"""erp_leave_balances - materialized current balance per (employee, leave_type).

The CHECK ``balance >= 0`` is the integrity backstop for the no-negative-balance
rule; the service recomputes these rows from ``erp_leave_movements``. Only
``is_accrual`` leave types have balance rows (non-accrual types are ledger-only).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class LeaveBalanceModel(Base):
    """Current materialized balance for one employee + leave type."""

    __tablename__ = "erp_leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "employee_id", "leave_type", name="uq_erp_leave_balances_employee_type"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_leave_balances_employee",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "leave_type"],
            ["erp_leave_types.tenant_id", "erp_leave_types.code"],
            name="fk_erp_leave_balances_leave_type",
        ),
        CheckConstraint("balance >= 0", name="ck_erp_leave_balances_non_negative"),
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
    balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
