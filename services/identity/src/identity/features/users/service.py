"""User service — profile and credential management.

Owns the business rules (password verification, not-found handling). All
persistence goes through the ``UserRepositoryPort``; no ORM models or sessions
are touched here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from identity.core.security import hash_password, verify_password
from skyrict_common.exceptions import InvalidPasswordError, UserNotFoundError

if TYPE_CHECKING:
    import uuid

    from identity.domain.entities import User
    from identity.features.users.ports import UserRepositoryPort
    from identity.features.users.schemas import UserUpdateRequest


class UserService:
    """Encapsulates user profile and password-change business rules."""

    def __init__(self, user_repo: UserRepositoryPort) -> None:
        self.user_repo = user_repo

    async def get_profile(self, user_id: str | uuid.UUID) -> User:
        """Fetch a user profile, raising UserNotFoundError when absent."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    async def update_profile(self, user_id: str | uuid.UUID, body: UserUpdateRequest) -> User:
        """Apply the provided profile changes and persist them."""
        return await self.user_repo.update_profile(
            user_id,
            full_name=body.full_name,
            email=body.email,
        )

    async def change_password(
        self, user_id: str | uuid.UUID, current_password: str, new_password: str
    ) -> None:
        """Verify the current password and store a hash of the new one."""
        user = await self.get_profile(user_id)
        if not verify_password(current_password, user.password_hash):
            raise InvalidPasswordError("Current password is incorrect")
        await self.user_repo.update_password_hash(user_id, hash_password(new_password))
