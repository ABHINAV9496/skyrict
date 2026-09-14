"""erp_approval_workflow_instances - one submission through an approval chain.

A row is created when a module submits a resource (journal entry, payroll
run) to the engine. ``definition_id`` + ``definition_version`` pin the exact
definition the instance executed (versioned definitions are immutable, so the
pin is enough to replay history). ``status`` moves pending -> auto_approved /
approved / rejected / request_changes / cancelled; ``current_step_index``
points at the step awaiting action (or past the final step on completion).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpApprovalWorkflowInstanceModel(Base):
    """One approval workflow run bound to a tenant and resource."""

    __tablename__ = "erp_approval_workflow_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'auto_approved', 'approved', "
            "'rejected', 'request_changes', 'cancelled')",
            name="ck_erp_approval_workflow_instances_status",
        ),
        CheckConstraint(
            "current_step_index >= 0",
            name="ck_erp_approval_workflow_instances_current_step_index",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default=text("'pending'")
    )
    current_step_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
