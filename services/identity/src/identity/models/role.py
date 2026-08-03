"""Role ORM model for RBAC."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, false, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from identity.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RoleModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SQLAlchemy model for the roles table.

    Role names are unique per tenant (``(tenant_id, name)``). The
    ``permissions`` array holds keys from the platform-fixed permission
    catalog (see the ``permissions`` table).
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'")
    )
    is_system_role: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Relationships
    tenant = relationship("TenantModel", back_populates="roles")
    user_roles = relationship("UserRoleModel", back_populates="role", lazy="selectin")
