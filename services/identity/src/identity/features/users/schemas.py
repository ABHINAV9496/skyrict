"""User schemas — requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserUpdateRequest(BaseModel):
    """PUT /users/me"""

    full_name: str | None = Field(default=None, min_length=1, max_length=256)
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    """POST /users/me/password"""

    current_password: str
    new_password: str = Field(..., min_length=8)


class UserResponse(BaseModel):
    """User data returned in API responses."""

    id: UUID
    email: str
    full_name: str
    is_active: bool
    is_verified: bool
    mfa_enabled: bool
    onboarding_dismissed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Paginated user list."""

    items: list[UserResponse]
    total: int
    page: int
    page_size: int
