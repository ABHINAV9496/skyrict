"""erp_crm_timeline_events - curated business events for the CRM timeline.

Tenant-scoped with RLS and the composite ``(tenant_id, id)`` primary key.
This is the customer-facing CRM history log: written transactionally inside
the same request as the business action. It is a SEPARATE concept from:

- the security/compliance ``audit_logs`` trail (never a CRM timeline source);
- the async ``crm.*`` domain events (bus-only, after-commit).

``entity_type`` is one of ``lead|opportunity|customer|contact`` - order
creations anchor to the related customer, never an ``order`` entity type.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import CrmEntityType, CrmTimelineEventType
from core.models.base import Base


class ErpCrmTimelineEventModel(Base):
    __tablename__ = "erp_crm_timeline_events"
    __table_args__ = (
        Index(
            "ix_erp_crm_timeline_tenant_entity_created",
            "tenant_id",
            "entity_type",
            "entity_id",
            "created_at",
        ),
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
    event_type: Mapped[CrmTimelineEventType] = mapped_column(
        Enum(
            CrmTimelineEventType,
            name="erp_crm_timeline_event_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
