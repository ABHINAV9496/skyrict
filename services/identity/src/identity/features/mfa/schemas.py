"""MFA (Multi-Factor Authentication) request/response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from identity.core.mfa_providers import PROVIDER_TOTP, available_provider_keys


class MFASetupResponse(BaseModel):
    """POST /mfa/setup — TOTP secret, otpauth URI, and one-time backup codes.

    ``secret`` and ``backup_codes`` are shown once and never returned again.
    """

    secret: str = Field(..., description="TOTP secret — encrypted at rest after this response")
    provisioning_uri: str = Field(..., description="otpauth:// URI for QR code enrollment")
    backup_codes: list[str] = Field(..., description="10 one-time backup codes (shown once)")


class MFAVerifyRequest(BaseModel):
    """POST /mfa/verify — a 6-digit TOTP code or a one-time backup code."""

    code: str = Field(..., min_length=6, max_length=32, description="TOTP code or backup code")


class MFAVerifyResponse(BaseModel):
    """Result of MFA verification during setup/enablement."""

    verified: bool = True
    method: str = Field(
        ...,
        description=f"Verified provider key: {PROVIDER_TOTP!r} or {available_provider_keys()!r}",
    )


class MFADisableRequest(BaseModel):
    """POST /mfa/disable — password confirmation required."""

    password: str = Field(..., min_length=1, description="Current password")


class MFAResetRequest(BaseModel):
    """POST /mfa/reset — owner-assisted reset for a locked-out user."""

    user_id: UUID = Field(..., description="Target user whose MFA is reset")
