"""erp_crm_notes - persistent free-form notes on CRM entities.

Tenant-scoped with RLS and the composite ``(tenant_id, id)`` primary key.
``author_id`` records the writer (plain UUID, no FK). ``entity_type`` /
``entity_id`` anchor the note to exactly one CRM entity; ``body`` must be
non-empty (DB CHECK).

Separate from ``kind='note'`` activities: activities are timeline interactions
with an actor/timestamp, notes are the persistent per-entity note feature.
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

from core.domain.value_objects import CrmEntityType
from core.models.base import Base


class ErpCrmNoteModel(Base):
    __tablename__ = "erp_crm_notes"
    __table_args__ = (
        CheckConstraint("body IS NOT NULL AND body <> ''", name="ck_erp_crm_notes_body_present"),
        Index("ix_erp_crm_notes_tenant_entity", "tenant_id", "entity_type", "entity_id"),
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
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
