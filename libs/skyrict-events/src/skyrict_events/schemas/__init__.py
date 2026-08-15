"""Event schemas for Skyrict domain events.

Each event model:
1. Inherits from `BaseEvent`
2. Sets `event_type` as a class-level constant
3. Adds domain-specific fields
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from skyrict_events.base import BaseEvent

TENANT_PROVISIONED_EVENT_TYPE = "identity.tenant.provisioned"
RBAC_ROLE_GRANTED_EVENT_TYPE = "identity.rbac.role_granted"


class RoleGrant(BaseModel):
    """One role + (optional) user grant snapshot inside an RBAC event.

    ``user_id`` is set when the role is granted to a user (e.g. the tenant
    owner at provisioning); ``scope_id`` mirrors the identity grant scope
    (tenant id for tenant-scoped grants). Consumers upsert the role and,
    when ``user_id`` is present, the user->role grant.
    """

    role_id: str = Field(..., description="Identity role UUID (reused as the core role id)")
    role_name: str = Field(..., description="Role name (tenant-unique)")
    permissions: list[str] = Field(default_factory=list, description="Granted permission keys")
    is_system_role: bool = Field(default=True, description="Platform-defined role flag")
    user_id: str | None = Field(default=None, description="User granted this role, if any")
    scope_id: str | None = Field(
        default=None, description="Grant scope id (tenant id when tenant-scoped)"
    )


class UserCreated(BaseEvent):
    """Published when a new user is registered."""

    event_type: str = "identity.user.created"
    user_id: str
    email: str
    full_name: str | None = None


class UserUpdated(BaseEvent):
    """Published when a user profile is updated."""

    event_type: str = "identity.user.updated"
    user_id: str
    changes: dict[str, object] | None = None


class AuthLoginSuccess(BaseEvent):
    """Published on successful login."""

    event_type: str = "identity.auth.login_success"
    user_id: str
    ip_address: str | None = None
    user_agent: str | None = None


class AuthLoginFailed(BaseEvent):
    """Published on failed login attempt."""

    event_type: str = "identity.auth.login_failed"
    user_id: str | None = None
    reason: str = "invalid_credentials"
    ip_address: str | None = None


class TenantCreated(BaseEvent):
    """Published when a new tenant (organization) is created."""

    event_type: str = "identity.tenant.created"
    tenant_id: str
    name: str
    slug: str


class TenantProvisioned(BaseEvent):
    """Published after a tenant's system roles + owner grant are provisioned.

    Carries the full role snapshot so a consumer (e.g. the core service's RBAC
    mirror) can provision its own ``core_roles`` / ``core_user_roles`` rows in
    one step. Incremental grants are published separately as
    :class:`RbacRoleGranted`.
    """

    event_type: str = TENANT_PROVISIONED_EVENT_TYPE
    slug: str
    role_grants: list[RoleGrant]


class RbacRoleGranted(BaseEvent):
    """Published when a role is granted to a user within a tenant scope."""

    event_type: str = RBAC_ROLE_GRANTED_EVENT_TYPE
    grant: RoleGrant


class SessionCreated(BaseEvent):
    """Published when a user session is created."""

    event_type: str = "identity.session.created"
    user_id: str
    session_id: str
    ip_address: str | None = None


class SessionRevoked(BaseEvent):
    """Published when a user session is revoked."""

    event_type: str = "identity.session.revoked"
    user_id: str
    session_id: str
    reason: str | None = None


class MFASuccess(BaseEvent):
    """Published when MFA verification succeeds."""

    event_type: str = "identity.mfa.success"
    user_id: str
    method: str = "totp"


class MFAFailed(BaseEvent):
    """Published when MFA verification fails."""

    event_type: str = "identity.mfa.failed"
    user_id: str
    method: str = "totp"
    reason: str = "invalid_code"


__all__ = [
    "RBAC_ROLE_GRANTED_EVENT_TYPE",
    "TENANT_PROVISIONED_EVENT_TYPE",
    "AuthLoginFailed",
    "AuthLoginSuccess",
    "MFAFailed",
    "MFASuccess",
    "RbacRoleGranted",
    "RoleGrant",
    "SessionCreated",
    "SessionRevoked",
    "TenantCreated",
    "TenantProvisioned",
    "UserCreated",
    "UserUpdated",
]
