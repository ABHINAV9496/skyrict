"""erp_crm_activities - unified CRM activity rows (task/call/meeting/etc.).

Tenant-scoped with RLS and the composite ``(tenant_id, id)`` primary key.
Follow-ups are ``kind = 'follow_up'`` rows with a ``due_at`` - there is no
separate follow-up table. Owner/team-scoped like leads/opportunities, so the
repository reuses the same OWNER/TEAM/ALL filter on ``owner_id``/``team_id``;
a row created without an owner is tenant-visible.

``entity_type``/``entity_id`` anchor the activity to exactly one CRM entity
(lead/opportunity/customer/contact). ``completed_at`` and ``completed_by`` are
set together by the complete action (DB CHECK); ``due_at`` is optional (only
tasks/follow-ups carry a deadline).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import ActivityKind, CrmEntityType
from core.models.base import Base


class ErpCrmActivityModel(Base):
    __tablename__ = "erp_crm_activities"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NULL OR completed_by IS NOT NULL",
            name="ck_erp_crm_activities_completed_pair",
        ),
        Index(
            "ix_erp_crm_activities_tenant_entity",
            "tenant_id",
            "entity_type",
            "entity_id",
        ),
        Index("ix_erp_crm_activities_tenant_owner_due", "tenant_id", "owner_id", "due_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    kind: Mapped[ActivityKind] = mapped_column(
        Enum(
            ActivityKind,
            name="erp_crm_activity_kind",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    entity_type: Mapped[CrmEntityType] = mapped_column(
        Enum(
            CrmEntityType,
            name="erp_crm_entity_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
