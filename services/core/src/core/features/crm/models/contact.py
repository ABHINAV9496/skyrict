"""erp_crm_contacts — people on a customer account, tenant-scoped with RLS.

A customer is the account; a contact is a person who works there. Tenant-scoped
with the composite primary key ``(tenant_id, id)`` convention and soft-deleted
via ``is_active`` (no status enum — mirrors ``erp_crm_customers``).
``customer_id`` is a plain UUID anchor with NO FK (same convention as
``source_opportunity_id`` in migration 0015).

The ``(tenant_id, email)`` index is deliberately NON-unique: email dedupe stays
a soft service-layer probe, exactly like ``erp_crm_leads``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class ErpCrmContactModel(Base):
    __tablename__ = "erp_crm_contacts"
    __table_args__ = (
        CheckConstraint(
            "(first_name IS NOT NULL AND first_name <> '')"
            " OR (last_name IS NOT NULL AND last_name <> '')"
            " OR (email IS NOT NULL AND email <> '')",
            name="ck_erp_crm_contacts_identity_present",
        ),
        Index("ix_erp_crm_contacts_tenant_customer", "tenant_id", "customer_id"),
        Index("ix_erp_crm_contacts_tenant_email", "tenant_id", "email"),
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
    # customer_id: soft link to the owning account (plain UUID, NO FK).
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
