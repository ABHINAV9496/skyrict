"""Authentication schemas — requests, responses, and token payloads."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from identity.features.users.schemas import UserResponse


class LoginRequest(BaseModel):
    """POST /auth/login"""

    email: EmailStr
    password: str = Field(..., min_length=1)
    tenant_slug: str | None = Field(default=None, description="Tenant slug for multi-tenant login")


class RegisterRequest(BaseModel):
    """POST /auth/register — self-service tenant provisioning."""

    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=256)
    organization_name: str = Field(..., min_length=1, max_length=256)


class VerifyEmailRequest(BaseModel):
    """POST /auth/verify-email"""

    token: str


class RegisterResponse(BaseModel):
    """Response after successful self-service registration.

    The account starts unverified and must confirm the email before login.
    ``verification_token`` is exposed only outside production (dev/test).
    """

    email: EmailStr
    user_id: UUID
    tenant_id: UUID
    tenant_slug: str
    verification_pending: bool = True
    verification_token: str | None = None
    expires_in: int = Field(..., description="Verification token TTL in seconds")


class VerifyEmailResponse(BaseModel):
    """Response after a successful (or idempotent) email verification."""

    verified: bool = True


class TokenRefreshRequest(BaseModel):
    """POST /auth/refresh"""

    refresh_token: str


class LogoutRequest(BaseModel):
    """POST /auth/logout"""

    refresh_token: str | None = Field(
        default=None, description="Specific token to revoke; if omitted, revoke all"
    )


class TokenPayloadSchema(BaseModel):
    """Decoded JWT payload."""

    sub: str
    tenant_id: str
    type: str  # "access" or "refresh"
    exp: int
    iat: int


class TokenIntrospectionResponse(BaseModel):
    """POST /auth/introspect — token introspection."""

    active: bool
    sub: str | None = None
    tenant_id: str | None = None
    type: str | None = None
    exp: int | None = None
    scope: str | None = None


class AuthResponse(BaseModel):
    """Response after successful login/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(default=900, description="Access token TTL in seconds")
    mfa_required: bool = Field(
        default=False,
        description="True when MFA setup is mandatory for this account (tenant owners or tenant policy)",
    )
    next_step: str | None = Field(
        default=None,
        description='Required next step when mfa_required — e.g. "mfa.setup"',
    )
    user: UserResponse | None = None
