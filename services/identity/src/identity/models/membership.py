"""Membership ORM model — a user's relationship with a tenant.

The single source of membership truth: ``users.tenant_id`` stays denormalized
for Row-Level Security simplicity, but the membership lifecycle (invited ->
active -> suspended) is owned here.

``user_id`` is NULL while INVITED (no placeholder users — invitations carry
the pending relationship); ``invited_email`` reserves the email within the
tenant. ``role_id`` is the membership's primary role (denormalized from
``user_roles``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from identity.domain.entities import MembershipStatus
from identity.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MembershipModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SQLAlchemy model for the memberships table."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
        UniqueConstraint("tenant_id", "invited_email", name="uq_memberships_tenant_email"),
        CheckConstraint(
            "user_id IS NOT NULL OR invited_email IS NOT NULL",
            name="ck_memberships_user_or_email",
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invited_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        SAEnum(
            MembershipStatus,
            name="membership_status",
            create_type=False,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=MembershipStatus.ACTIVE,
    )
    invited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("UserModel", back_populates="memberships")
    tenant = relationship("TenantModel", back_populates="memberships")
    role = relationship("RoleModel")
    invited_by = relationship("UserModel", foreign_keys=[invited_by_user_id])
