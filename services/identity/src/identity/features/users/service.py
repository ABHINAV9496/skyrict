"""User service — profile and credential management."""

from __future__ import annotations

from typing import TYPE_CHECKING

from identity.core.security import hash_password, verify_password
from skyrict_common.exceptions import InvalidPasswordError, UserNotFoundError

if TYPE_CHECKING:
    import uuid

    from identity.features.users.repository import UserRepository
    from identity.features.users.schemas import UserUpdateRequest
    from identity.models.user import UserModel


class UserService:
    """Encapsulates user profile and password-change business rules."""

    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def get_profile(self, user_id: str | uuid.UUID) -> UserModel:
        """Fetch a user profile, raising UserNotFoundError when absent."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        return user

    async def update_profile(self, user_id: str | uuid.UUID, body: UserUpdateRequest) -> UserModel:
        """Apply the provided profile changes and persist them."""
        user = await self.get_profile(user_id)
        if body.full_name is not None:
            user.full_name = body.full_name
        if body.email is not None:
            user.email = body.email
        await self.user_repo.commit()
        return user

    async def change_password(
        self, user_id: str | uuid.UUID, current_password: str, new_password: str
    ) -> None:
        """Verify the current password and store a hash of the new one."""
        user = await self.get_profile(user_id)
        if not verify_password(current_password, user.password_hash):
            raise InvalidPasswordError("Current password is incorrect")
        user.password_hash = hash_password(new_password)
        await self.user_repo.commit()
