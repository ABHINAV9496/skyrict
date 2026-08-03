"""Authentication schemas — requests, responses, and token payloads."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from identity.features.users.schemas import UserResponse


class LoginRequest(BaseModel):
    """POST /auth/login"""

    email: EmailStr
    password: str = Field(..., min_length=1)
    tenant_slug: str | None = Field(default=None, description="Tenant slug for multi-tenant login")


class RegisterRequest(BaseModel):
    """POST /auth/register"""

    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=256)
    tenant_slug: str | None = Field(default=None, description="Join existing tenant or create new")


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
    """Response after successful login/register/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(default=900, description="Access token TTL in seconds")
    user: UserResponse | None = None
