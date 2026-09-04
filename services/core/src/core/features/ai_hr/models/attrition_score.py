"""ai_hr_attrition_scores - per-employee attrition risk.

Written by the attrition model (Commit 3); read for both the L1 team-risk
list (grouped by department/band) and the L2 per-employee view. `department_id`
is denormalized for L1 grouping and deliberately has no hard FK (departments
may be soft-disabled). `factors` is the top-3 SHAP-style contribution list.
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
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class AttritionRiskBand:
    """Valid risk bands for ``ai_hr_attrition_scores.risk_band``."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AttritionScoreModel(Base):
    """A single model run's score for one employee."""

    __tablename__ = "ai_hr_attrition_scores"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "employee_id"],
            ["erp_employees.tenant_id", "erp_employees.id"],
            name="fk_ai_hr_attrition_scores_employee",
        ),
        CheckConstraint(
            "risk_band IN ('low', 'medium', 'high')",
            name="ck_ai_hr_attrition_scores_risk_band",
        ),
        UniqueConstraint(
            "tenant_id",
            "employee_id",
            "model_version",
            name="uq_ai_hr_attrition_scores_employee_model",
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
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    score: Mapped[object] = mapped_column(Numeric(5, 4), nullable=False)
    risk_band: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[object] = mapped_column(Numeric(3, 2), nullable=False)
    factors: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    acknowledged: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
