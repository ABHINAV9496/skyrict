"""erp_approval_transitions - append-only audit trail of every state change.

One row per engine action: submission, per-step approval/rejection, auto
approval, escalation, cancellation. ``actor_type`` distinguishes who decided:

- ``human`` - an approver decided.
- ``delegated`` - a delegate decided (``delegated_actor`` carries the delegate,
  ``actor_id`` the recorded actor).
- ``system`` - the engine itself (auto-approval, escalation automation).
- ``ai_suggestion`` - never an authority: records that an AI suggestion was
  considered and validated (or rejected) by the engine.
- ``escalation`` - SLA-breach reassignment.

``context`` stores the evaluated routing facts (amount, matching conditions)
as JSONB so history remains replayable without re-deriving.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpApprovalTransitionModel(Base):
    """Append-only engine audit record."""

    __tablename__ = "erp_approval_transitions"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('human', 'delegated', 'system', 'ai_suggestion', 'escalation')",
            name="ck_erp_approval_transitions_actor_type",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'human'")
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_assignee: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    delegated_actor: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
