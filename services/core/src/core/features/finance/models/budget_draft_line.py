"""erp_budget_draft_lines - cost-component lines of a proposed budget draft (SKY-93).

Each line represents one cost component (salary, benefits) from the L4 what-if
projection.  ``(draft_id, line_no)`` is the line identity; the composite FK
``(tenant_id, draft_id)`` means a line can only reference a draft in the same
tenant, and CASCADE drops lines with their draft.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpBudgetDraftLineModel(Base):
    __tablename__ = "erp_budget_draft_lines"
    __table_args__ = (
        PrimaryKeyConstraint("draft_id", "line_no"),
        ForeignKeyConstraint(
            ["tenant_id", "draft_id"],
            ["erp_budget_drafts.tenant_id", "erp_budget_drafts.id"],
            ondelete="CASCADE",
            name="fk_budget_draft_lines_draft",
        ),
        Index("ix_budget_draft_lines_draft", "tenant_id", "draft_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), nullable=False)