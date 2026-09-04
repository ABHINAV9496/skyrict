"""Tenant-scoped user→role grant model - RLS-protected, composite key.

``tenant_id`` is both the isolation column and a member of the primary key
(composite-PK RLS convention). The reference to its parent role is a COMPOSITE
foreign key ``(tenant_id, role_id) -> core_roles(tenant_id, id)`` so a grant can
only ever point at a role in the same tenant - referential integrity agrees
with RLS, closing the cross-tenant reference hole at the constraint level.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.models.base import Base


class CoreUserRoleModel(Base):
    """A grant of one tenant-scoped role to one user.

    ``user_id`` references an identity-service user. There is deliberately no
    FK to identity's users table (identity owns users in its own schema).
    """

    __tablename__ = "core_user_roles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "role_id", "scope_id", name="uq_core_user_roles_scope"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "role_id"],
            ["core_roles.tenant_id", "core_roles.id"],
            ondelete="CASCADE",
            name="fk_core_user_roles_role_tenant",
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
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
