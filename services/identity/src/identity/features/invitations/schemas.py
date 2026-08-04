"""Invitation schemas — requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role_name: str = Field(default="viewer", description="Role to assign on accept")


class InvitationAcceptRequest(BaseModel):
    token: str
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=256)


class InvitationResponse(BaseModel):
    id: UUID
    email: EmailStr
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
