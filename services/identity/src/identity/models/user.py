"""User ORM model."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, false, true
from sqlalchemy.dialects.postgresql import ARRAY, TEXT, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from identity.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SQLAlchemy model for the users table.

    Emails are unique per tenant (``(tenant_id, email)``), not globally.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    mfa_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phone_country: Mapped[str | None] = mapped_column(String(4), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(24), nullable=True)
    mfa_backup_codes: Mapped[list[str | None] | None] = mapped_column(ARRAY(TEXT), nullable=True)

    # Relationships
    tenant = relationship("TenantModel", back_populates="users")
    sessions = relationship("SessionModel", back_populates="user", lazy="selectin")
    user_roles = relationship("UserRoleModel", back_populates="user", lazy="selectin")
    audit_logs = relationship("AuditLogModel", back_populates="actor_user", lazy="selectin")
