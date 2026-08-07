"""Tenant (Organization) ORM model."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, String, false, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from identity.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SQLAlchemy model for the tenants table."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "plan_tier IN ('free', 'starter', 'professional', 'business', 'enterprise')",
            name="ck_tenants_plan_tier",
        ),
    )

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plan_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    billing_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    mfa_required_for_all_members: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    # Relationships
    users = relationship("UserModel", back_populates="tenant", lazy="selectin")
    memberships = relationship("MembershipModel", back_populates="tenant", lazy="selectin")
    roles = relationship("RoleModel", back_populates="tenant", lazy="selectin")
    user_roles = relationship("UserRoleModel", back_populates="tenant", lazy="selectin")
    sessions = relationship("SessionModel", back_populates="tenant", lazy="selectin")
    audit_logs = relationship("AuditLogModel", back_populates="tenant", lazy="selectin")
    invitations = relationship("InvitationModel", back_populates="tenant", lazy="selectin")
