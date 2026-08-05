"""Organization (tenant) schemas — requests and responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TenantCreateRequest(BaseModel):
    """POST /organizations"""

    name: str = Field(..., min_length=1, max_length=256)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")


class TenantUpdateRequest(BaseModel):
    """PUT /organizations/{id}"""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    plan: str | None = None


class TenantSettingsUpdateRequest(BaseModel):
    """PATCH /tenants/{id}/settings — tenant security policy."""

    mfa_required_for_all_members: bool = Field(
        ...,
        description="When true, every non-owner member must set up MFA to sign in",
    )


class TenantResponse(BaseModel):
    """Tenant data returned in API responses."""

    id: UUID
    name: str
    slug: str
    is_active: bool
    plan_tier: str
    mfa_required_for_all_members: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
