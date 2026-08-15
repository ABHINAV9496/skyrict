"""Member management schemas — requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MemberResponse(BaseModel):
    """A workspace member row for the members list."""

    id: UUID
    email: str
    full_name: str
    role_name: str
    joined_at: datetime | None
    avatar_url: str | None = None
    is_self: bool = False


class MemberRoleUpdateRequest(BaseModel):
    """PATCH /members/{user_id}/role"""

    role_name: str = Field(..., min_length=1, max_length=100)
