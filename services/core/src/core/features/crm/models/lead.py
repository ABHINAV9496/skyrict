"""erp_crm_leads - inbound inquiries before they have pipeline value.

Tenant-scoped, RLS-protected, composite primary key ``(tenant_id, id)``
following the 0001 convention. ``owner_id`` / ``team_id`` are plain UUIDs with
no FK: they reference identity users (and a teams model that does not exist
yet) in the shared database, validated via ports at the service layer.

The ``(tenant_id, email)`` index is deliberately NON-unique: email dedupe is a
soft service-layer probe, never a uniqueness constraint. The DB CHECK
``ck_erp_crm_leads_contact_present`` requires at least one contact channel
(name or email) so a lead row is always identifiable.
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
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.domain.value_objects import LeadStatus
from core.models.base import Base


class ErpCrmLeadModel(Base):
    __tablename__ = "erp_crm_leads"
    __table_args__ = (
        CheckConstraint(
            "(first_name IS NOT NULL AND first_name <> '')"
            " OR (last_name IS NOT NULL AND last_name <> '')"
            " OR (email IS NOT NULL AND email <> '')",
            name="ck_erp_crm_leads_contact_present",
        ),
        Index("ix_erp_crm_leads_tenant_email", "tenant_id", "email"),
        Index("ix_erp_crm_leads_tenant_owner", "tenant_id", "owner_id"),
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
    status: Mapped[LeadStatus] = mapped_column(
        Enum(
            LeadStatus,
            name="erp_crm_lead_status",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=text("'new'"),
    )
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
