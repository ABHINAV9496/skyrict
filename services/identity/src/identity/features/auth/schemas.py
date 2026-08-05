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
    email: EmailStr
    password: str = Field(..., min_length=1)
    tenant_slug: str | None = Field(default=None, description="Tenant slug for multi-tenant login")


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(
        default=None, description="Specific token to revoke; if omitted, revoke all"
    )


class TokenPayloadSchema(BaseModel):
    sub: str
    tenant_id: str
    type: str
    exp: int
    iat: int


class TokenIntrospectionResponse(BaseModel):
    active: bool
    sub: str | None = None
    tenant_id: str | None = None
    type: str | None = None
    exp: int | None = None
    scope: str | None = None


class AuthResponse(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int = Field(default=900, description="Access token TTL in seconds")
    mfa_required: bool = Field(
        default=False,
        description="True when MFA must be satisfied before tokens are usable",
    )
    mfa_token: str | None = Field(
        default=None,
        description='Single-use challenge token when next_step is "mfa.verify"',
    )
    next_step: str | None = Field(
        default=None,
        description='Required next step when mfa_required — "mfa.setup" or "mfa.verify"',
    )
    user: UserResponse | None = None


class MfaChallengeVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=32, description="TOTP code or backup code")
    mfa_token: str = Field(..., description="Opaque challenge token from the login response")


class SignupStartRequest(_CamelModel):
    email: EmailStr
    turnstile_token: str | None = Field(default=None, description="Cloudflare Turnstile response")


class SignupStartResponse(_CamelModel):
    status: Literal["ok"] = "ok"


class SendCodeRequest(_CamelModel):
    email: EmailStr


class SendCodeResponse(_CamelModel):
    status: Literal["ok"] = "ok"
    resend_in: int = Field(default=60, description="Seconds until a new code can be sent")
    code: str | None = Field(default=None, description="Plaintext OTP, dev/test only")


class VerifyCodeRequest(_CamelModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6)


class VerifyCodeResponse(_CamelModel):
    status: Literal["ok", "invalid", "expired"]
    verification_token: str | None = Field(default=None, description="Opaque single-use token")


class SetPasswordRequest(_CamelModel):
    email: EmailStr
    verification_token: str
    password: str = Field(..., min_length=12)


class SetPasswordResponse(_CamelModel):
    status: Literal["ok"] = "ok"


class CheckEmailRequest(_CamelModel):
    email: EmailStr


class CheckEmailResponse(_CamelModel):
    available: bool


class CheckSlugRequest(_CamelModel):
    slug: str = Field(..., min_length=1, max_length=100)


class CheckSlugResponse(_CamelModel):
    available: bool


class BillingAddress(_CamelModel):
    country: str = Field(..., min_length=2, max_length=2)
    address_line1: str = Field(..., min_length=1, max_length=256)
    address_line2: str | None = Field(default=None, max_length=256)
    city: str = Field(..., min_length=1, max_length=120)
    state: str = Field(..., min_length=1, max_length=120)
    postal_code: str = Field(..., min_length=1, max_length=24)


class CreateOrganizationRequest(_CamelModel):
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
    status: Literal["ok"] = "ok"
    mfa_required: bool = True
    tenant_id: UUID
    tenant_slug: str
