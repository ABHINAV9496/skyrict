"""Domain entities — pure Python dataclasses, no framework dependencies.

These represent the core business objects of the identity domain.
Services operate on these, not on ORM models directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


class ScopeType(Enum):
    """Scope an RBAC grant applies to."""

    TENANT = "tenant"
    ORG = "org"
    WORKSPACE = "workspace"
    DEPARTMENT = "department"
    TEAM = "team"


class MembershipStatus(Enum):
    """Lifecycle state of a user's membership in a tenant."""

    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"


@dataclass
class Membership:
    """Membership entity — a user's relationship with a tenant.

    ``user_id`` is NULL while the membership is INVITED (no placeholder users:
    invitations carry the pending relationship, users materialize on accept).
    ``invited_email`` reserves the email within the tenant. ``role_id`` is the
    membership's primary role. Lifecycle: invited -> active -> (suspended <->
    active).
    """

    tenant_id: UUID
    invited_email: str | None = None
    user_id: UUID | None = None
    status: MembershipStatus = MembershipStatus.ACTIVE
    role_id: UUID | None = None
    invited_by_user_id: UUID | None = None
    invited_at: datetime | None = None
    joined_at: datetime | None = None
    suspended_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None

    def __post_init__(self) -> None:
        if self.user_id is None and not self.invited_email:
            raise ValueError("A membership needs a user_id or an invited_email")
        if self.user_id is None and self.status is not MembershipStatus.INVITED:
            raise ValueError("A membership without a user must be INVITED")


@dataclass
class User:
    """User entity."""

    tenant_id: UUID
    email: str
    password_hash: str
    full_name: str
    is_active: bool = True
    is_verified: bool = False
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    phone_country: str | None = None
    phone_number: str | None = None
    mfa_backup_codes: list[str | None] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None


@dataclass
class Tenant:
    """Tenant (organization) entity."""

    name: str
    slug: str
    is_active: bool = True
    plan_tier: str = "free"
    industry: str | None = None
    billing_address: dict[str, Any] | None = None
    mfa_required_for_all_members: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None


@dataclass
class Session:
    """User session entity."""

    user_id: UUID
    tenant_id: UUID
    refresh_token_hash: str
    user_agent: str | None = None
    device_info: dict[str, Any] | None = None
    ip_address: str | None = None
    location: str | None = None
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_active_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None
    id: UUID | None = None


@dataclass
class Role:
    """Role entity for RBAC."""

    tenant_id: UUID
    name: str
    permissions: list[str] = field(default_factory=list)
    is_system_role: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None


@dataclass
class Permission:
    """Platform-fixed permission catalog entry (no tenant)."""

    id: UUID
    key: str
    description: str = ""


@dataclass
class UserRole:
    """Grant of a role to a user within a scope."""

    id: UUID
    user_id: UUID
    role_id: UUID
    tenant_id: UUID
    scope_type: ScopeType = ScopeType.TENANT
    scope_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Invitation:
    """Invitation entity — single-use, expiring invite token.

    ``membership_id`` links the invitation to its INVITED membership, which
    owns the pending relationship; the user materializes on accept.
    """

    tenant_id: UUID
    email: str
    token_hash: str
    role_name: str
    created_by_user_id: UUID
    expires_at: datetime
    id: UUID | None = None
    membership_id: UUID | None = None
    used_at: datetime | None = None
    used_by_user_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AuditLog:
    """Audit log entry entity — hash-chained, append-only."""

    tenant_id: UUID
    action: str
    target: str
    actor_user_id: UUID | None = None
    details: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    hash: str = ""
    prev_hash: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID | None = None
