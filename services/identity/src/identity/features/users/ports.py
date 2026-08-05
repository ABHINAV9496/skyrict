"""User repository port — the persistence contract the users service depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.users.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from identity.domain.entities import User

if TYPE_CHECKING:
    import uuid


class UserRepositoryPort(Protocol):
    """Persistence operations for users, tenant-scoped."""

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None: ...

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> User | None: ...

    async def email_exists(self, tenant_id: str | uuid.UUID, email: str) -> bool: ...

    async def create(self, user: User) -> User: ...

    async def update_profile(
        self,
        user_id: str | uuid.UUID,
        *,
        full_name: str | None = None,
        email: str | None = None,
    ) -> User: ...

    async def update_password_hash(self, user_id: str | uuid.UUID, password_hash: str) -> User: ...

    async def update_mfa(
        self,
        user_id: str | uuid.UUID,
        *,
        mfa_enabled: bool | None = None,
        mfa_secret: str | None = None,
        mfa_backup_codes: list[str | None] | None = None,
    ) -> User: ...

    async def disable_mfa(self, user_id: str | uuid.UUID) -> User: ...

    async def mark_verified(self, user_id: str | uuid.UUID) -> User: ...
