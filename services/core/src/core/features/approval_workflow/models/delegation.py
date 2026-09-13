"""erp_approval_delegations - runtime approver-level delegation (SKY-92).

A delegation record grants ``delegate`` the right to act on ``delegator``'s
behalf in the approval workflow, optionally scoped by ``permission`` and
``resource_type``, within an effective window. Delegation is runtime state:
it never rewrites workflow definitions or historical transitions, and it can
be revoked at any time (``revoked_at``).

Eligibility at decision time (fail closed):

- the delegation is active: ``revoked_at IS NULL`` and ``now`` lies within
  ``[effective_from, effective_to)``;
- the scopes match: ``resource_type`` is null or equals the instance's
  resource type, and ``permission`` is null or equals the step's permission
  key (permission-scoped grants only cover permission-keyed steps).

``created_by`` is required (audit contract); a delegation is created by the
delegator themselves or by an administrator on their behalf.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpApprovalDelegationModel(Base):
    """One runtime delegation grant (delegator -> delegate)."""

    __tablename__ = "erp_approval_delegations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    delegator: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delegate: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    permission: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
