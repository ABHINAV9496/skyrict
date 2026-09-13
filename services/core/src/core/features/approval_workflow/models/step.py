"""erp_approval_workflow_steps - per-instance step state.

Resolved at submission time from the definition's steps: the assignee
condition (kind + value), the SLA due time and the effective assignee. The
``original_assignee``/``assigned_to``/``delegated_from`` triple supports
runtime approver-level delegation: history always records who was originally
routed to, who decided, and which delegation rewired the step.

``status`` moves pending -> approved / rejected / skipped / escalated.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpApprovalWorkflowStepModel(Base):
    """One resolved step of an approval instance."""

    __tablename__ = "erp_approval_workflow_steps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'skipped', 'escalated')",
            name="ck_erp_approval_workflow_steps_status",
        ),
        CheckConstraint(
            "assignee_kind IN ('role', 'permission', 'users')",
            name="ck_erp_approval_workflow_steps_assignee_kind",
        ),
        UniqueConstraint(
            "instance_id", "step_index", name="uq_erp_approval_workflow_steps_instance_index"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    assignee_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'role'")
    )
    assignee_value: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=text("''")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    original_assignee: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    delegated_from: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
