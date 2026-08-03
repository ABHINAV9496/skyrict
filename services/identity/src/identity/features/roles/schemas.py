"""Role schemas — requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    """POST /roles — create a custom (non-system) role."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    permissions: list[str] = Field(default_factory=list)


class RoleResponse(BaseModel):
    """Role data returned in API responses."""

    id: UUID
    name: str
    permissions: list[str]
    is_system_role: bool
    created_at: datetime

    model_config = {"from_attributes": True}
