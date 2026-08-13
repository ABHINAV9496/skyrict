"""Invitation schemas — requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from identity.core.constants import DEFAULT_INVITE_ROLE


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role_name: str = Field(
        default=DEFAULT_INVITE_ROLE,
        description="Role to assign on accept — must exist in the organization",
    )


class InvitationVerifyResponse(BaseModel):
    """Token validation for the accept page (shown before account creation)."""

    valid: bool = True
    email: EmailStr
    role_name: str
    expires_at: datetime
    organization_name: str | None = None


class InvitationResponse(BaseModel):
    id: UUID
    token: str = Field(..., description="Plaintext invite token — shown once at create only")
    email: EmailStr
    role_name: str
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvitationSummaryResponse(BaseModel):
    """Invitation list item — never exposes the plaintext token."""

    id: UUID
    email: EmailStr
    role_name: str
    expires_at: datetime
    used_at: datetime | None
    used_by_user_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}
