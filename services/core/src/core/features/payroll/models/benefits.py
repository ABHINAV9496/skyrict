"""erp_benefit_plans / erp_benefit_elections — tenant benefit catalogue.

``erp_benefit_plans`` lists the plans a tenant offers; ``erp_benefit_elections``
records per-employee ``enrolled``/``waived`` elections effective-dated by
``effective_from``. The payroll pre-flight ``benefit_elections`` warning check
reads the enrolled elections for a period, so a roster employee holding none is
surfaced before a payroll run commits. ``monthly_cost_cents`` is integer cents
(Numeric), never a float.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base

BENEFIT_PLAN_TYPE_MEDICAL = "medical"
BENEFIT_PLAN_TYPE_DENTAL = "dental"
BENEFIT_PLAN_TYPE_RETIREMENT = "retirement"
BENEFIT_PLAN_TYPE_OTHER = "other"

BENEFIT_ELECTION_ENROLLED = "enrolled"
BENEFIT_ELECTION_WAIVED = "waived"


class BenefitPlanModel(Base):
    """A benefit plan a tenant offers (medical, retirement, ...)."""

    __tablename__ = "erp_benefit_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "plan_code", name="uq_erp_benefit_plans_tenant_code"),
        CheckConstraint(
            "plan_type IN ('medical', 'dental', 'retirement', 'other')",
            name="ck_erp_benefit_plans_type",
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
    plan_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    monthly_cost_cents: Mapped[Decimal | None] = mapped_column(Numeric(18, 0), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BenefitElectionModel(Base):
    """A per-employee election against a benefit plan."""

    __tablename__ = "erp_benefit_elections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "employee_id",
            "plan_id",
            "effective_from",
            name="uq_erp_benefit_elections_employee_plan_effective",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_erp_benefit_elections_employee",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "plan_id"],
            ["erp_benefit_plans.tenant_id", "erp_benefit_plans.id"],
            name="fk_erp_benefit_elections_plan",
        ),
        CheckConstraint(
            "status IN ('enrolled', 'waived')",
            name="ck_erp_benefit_elections_status",
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
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = [
    "BENEFIT_ELECTION_ENROLLED",
    "BENEFIT_ELECTION_WAIVED",
    "BENEFIT_PLAN_TYPE_DENTAL",
    "BENEFIT_PLAN_TYPE_MEDICAL",
    "BENEFIT_PLAN_TYPE_OTHER",
    "BENEFIT_PLAN_TYPE_RETIREMENT",
    "BenefitElectionModel",
    "BenefitPlanModel",
]
