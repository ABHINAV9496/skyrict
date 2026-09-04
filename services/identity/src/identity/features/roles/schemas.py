"""Role schemas - requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RoleCreateRequest(BaseModel):
    """POST /roles - create a custom (non-system) role."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_-]+$")
    permission_keys: list[str] = Field(..., min_length=1, max_length=64)

    model_config = ConfigDict(extra="forbid")


class RoleResponse(BaseModel):
    """Role data returned in API responses."""

    id: UUID
    name: str
    permissions: list[str]
    is_system_role: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MyRolesResponse(BaseModel):
    """The authenticated user's roles and effective permissions in a tenant."""

    roles: list[str]
    permissions: list[str]


class PermissionResponse(BaseModel):
    """Single permission in the catalog."""

    key: str
    description: str


class PermissionModule(BaseModel):
    """A module grouping related permissions."""

    key: str
    label: str
    permissions: list[PermissionResponse]


class PermissionCatalogResponse(BaseModel):
    """Full permission catalog for GET /permissions."""

    modules: list[PermissionModule]
