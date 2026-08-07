"""Membership repository port — dependency boundary for the membership feature."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from identity.domain.entities import Membership, MembershipStatus


class MembershipRepositoryPort(Protocol):
    """Persistence contract for memberships."""

    async def create(self, membership: Membership) -> Membership: ...

    async def get_by_id(self, membership_id: str | uuid.UUID) -> Membership | None: ...

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> Membership | None: ...

    async def get_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> Membership | None: ...

    async def list_by_tenant(
        self,
        tenant_id: str | uuid.UUID,
        *,
        status: MembershipStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Membership]: ...

    async def update_status(
        self,
        membership_id: str | uuid.UUID,
        *,
        status: MembershipStatus,
        suspended_at: datetime | None = None,
    ) -> Membership: ...

    async def set_user(
        self,
        membership_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        *,
        joined_at: datetime,
    ) -> Membership: ...
