"""User repository — DB operations for the users table.

All queries are tenant-scoped: when no tenant_id is passed the current
request tenant is used (see TenantContext) and RLS additionally enforces it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from identity.core.tenant_context import TenantContext
from identity.db.repository import BaseRepository
from identity.models.user import UserModel

if TYPE_CHECKING:
    import uuid


class UserRepository(BaseRepository[UserModel]):
    """Repository for user CRUD operations."""

    model = UserModel

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> UserModel | None:
        """Fetch a user by email within a tenant."""
        stmt = select(UserModel).where(
            UserModel.tenant_id == tenant_id,
            UserModel.email == email,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def email_exists(self, tenant_id: str | uuid.UUID, email: str) -> bool:
        """Check if a user with this email already exists within a tenant."""
        user = await self.get_by_email(tenant_id, email)
        return user is not None

    async def list_active(
        self,
        *,
        tenant_id: str | uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[UserModel]:
        """List all active users for a tenant."""
        tid: str | uuid.UUID = tenant_id or TenantContext.get()
        return list(
            await self.list(
                offset=offset,
                limit=limit,
                filters=[UserModel.is_active == True, UserModel.tenant_id == tid],  # noqa: E712
            )
        )
