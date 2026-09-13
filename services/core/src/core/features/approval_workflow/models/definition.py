"""erp_approval_workflow_definitions - versioned per-tenant approval DSL documents.

One row per approved/revisioned workflow definition version. ``definition``
holds the Pydantic-validated DSL body as JSONB; a version becomes immutable
once ``status = 'active'`` (the engine seals it at activation time) and edits
create a new version via ``UNIQUE (tenant_id, resource_type, version)``.

``created_by``/``updated_by`` record the acting identity (system actor for
seeded defaults) to satisfy core's audit convention.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpApprovalWorkflowDefinitionModel(Base):
    """Versioned approval workflow definition document (SKY-92)."""

    __tablename__ = "erp_approval_workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "resource_type",
            "version",
            name="uq_erp_approval_workflow_definitions_tenant_resource_version",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name="ck_erp_approval_workflow_definitions_status",
        ),
        CheckConstraint("version >= 1", name="ck_erp_approval_workflow_definitions_version"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, nullable=False
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
