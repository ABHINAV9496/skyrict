"""Tenant-scoped ERP role model — RLS-protected, composite primary key.

Composite PK ``(tenant_id, id)`` is part of the RLS convention: ``tenant_id``
is both the isolation column and a member of the key, so a row's tenant can
never be silently changed without rewriting its identity, and child tables can
reference it with a composite FK that keeps referential integrity aligned with
RLS (a cross-tenant child is impossible at the constraint level).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CoreRoleModel(Base):
    """A role within a tenant, holding a set of granted permission keys."""

    __tablename__ = "core_roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_core_roles_tenant_name"),)

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
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(
        postgresql.ARRAY(String()),
        nullable=False,
        server_default=text("'{}'"),
    )
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
