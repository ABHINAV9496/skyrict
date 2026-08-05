"""Authentication schemas — requests, responses, and token payloads."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AliasGenerator, BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from identity.features.users.schemas import UserResponse


class _CamelModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=AliasGenerator(validation_alias=to_camel, serialization_alias=to_camel),
    )


class LoginRequest(BaseModel):
    """POST /auth/login"""

    email: EmailStr
    password: str = Field(..., min_length=1)
    tenant_slug: str | None = Field(default=None, description="Tenant slug for multi-tenant login")


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


# ---------------------------------------------------------------------------
# Onboarding wizard schemas (SKY-30).
#
# The wizard is the web app's contract: its TypeScript client speaks camelCase
# (verificationToken, planId, ...), so these models alias snake_case Python
# fields to camelCase JSON while keeping idiomatic names in service code.
# ---------------------------------------------------------------------------


class SignupStartRequest(_CamelModel):
    """POST /auth/signup/start"""

    email: EmailStr
    turnstile_token: str | None = Field(default=None, description="Cloudflare Turnstile response")


class SignupStartResponse(_CamelModel):
    """Response after a successful Turnstile + email gate."""

    status: Literal["ok"] = "ok"


class SendCodeRequest(_CamelModel):
    """POST /auth/signup/send-code"""

    email: EmailStr


class SendCodeResponse(_CamelModel):
    """Response after an OTP is sent (or a resend is still cooling down).

    ``code`` is exposed only outside production (dev/test).
    """

    status: Literal["ok"] = "ok"
    resend_in: int = Field(default=60, description="Seconds until a new code can be sent")
    code: str | None = Field(default=None, description="Plaintext OTP, dev/test only")


class VerifyCodeRequest(_CamelModel):
    """POST /auth/signup/verify-code"""

    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class VerifyCodeResponse(_CamelModel):
    """Result of an OTP check — never reveals whether the email has an account."""

    status: Literal["ok", "invalid", "expired"]
    verification_token: str | None = Field(default=None, description="Opaque single-use token")


class SetPasswordRequest(_CamelModel):
    """POST /auth/signup/password"""

    email: EmailStr
    verification_token: str
    password: str = Field(..., min_length=12)


class SetPasswordResponse(_CamelModel):
    """Response after the wizard password is set."""

    status: Literal["ok"] = "ok"


class CheckEmailRequest(_CamelModel):
    """POST /auth/signup/check-email"""

    email: EmailStr


class CheckEmailResponse(_CamelModel):
    """Availability of an email for self-service signup."""

    available: bool


class CheckSlugRequest(_CamelModel):
    """POST /auth/signup/check-slug"""

    slug: str = Field(..., min_length=1, max_length=100)


class CheckSlugResponse(_CamelModel):
    """Availability of a workspace slug."""

    available: bool


class BillingAddress(_CamelModel):
    """Billing address captured on the organization step."""

    country: str = Field(..., min_length=2, max_length=2)
    address_line1: str = Field(..., min_length=1, max_length=256)
    address_line2: str | None = Field(default=None, max_length=256)
    city: str = Field(..., min_length=1, max_length=120)
    state: str = Field(..., min_length=1, max_length=120)
    postal_code: str = Field(..., min_length=1, max_length=24)


class CreateOrganizationRequest(_CamelModel):
    """POST /auth/signup/organization — final wizard step, provisions the tenant."""

    email: EmailStr
    verification_token: str
    plan_id: Literal["starter", "professional", "business", "enterprise"]
    company_name: str = Field(..., min_length=1, max_length=256)
    industry: str = Field(..., min_length=1, max_length=120)
    workspace_slug: str = Field(..., min_length=1, max_length=100)
    owner_full_name: str = Field(..., min_length=1, max_length=256)
    phone_country: str | None = Field(default=None, max_length=4)
    phone_number: str | None = Field(default=None, max_length=24)
    address: BillingAddress | None = None


class CreateOrganizationResponse(_CamelModel):
    """Response after the organization is provisioned — MFA setup is mandatory."""

    status: Literal["ok"] = "ok"
    mfa_required: bool = True
    tenant_id: UUID
    tenant_slug: str
