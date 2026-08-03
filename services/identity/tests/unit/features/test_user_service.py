"""Unit tests for the users feature service (fake UserRepositoryPort)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.security import hash_password, verify_password
from identity.domain.entities import User
from identity.features.users.schemas import UserUpdateRequest
from identity.features.users.service import UserService
from skyrict_common.exceptions import InvalidPasswordError, UserNotFoundError


class FakeUserRepo:
    """In-memory UserRepositoryPort double."""

    def __init__(self, users: list[User] | None = None) -> None:
        self.users: dict[uuid.UUID, User] = {}
        for user in users or []:
            if user.id is None:
                user.id = uuid.uuid4()
            self.users[user.id] = user
        self.created: list[User] = []

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None:
        return self.users.get(uuid.UUID(str(user_id)))

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> User | None:
        for user in self.users.values():
            if user.email == email and str(user.tenant_id) == str(tenant_id):
                return user
        return None

    async def email_exists(self, tenant_id: str | uuid.UUID, email: str) -> bool:
        return await self.get_by_email(tenant_id, email) is not None

    async def create(self, user: User) -> User:
        user.id = uuid.uuid4()
        self.users[user.id] = user
        self.created.append(user)
        return user

    async def update_profile(
        self,
        user_id: str | uuid.UUID,
        *,
        full_name: str | None = None,
        email: str | None = None,
    ) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        if full_name is not None:
            user.full_name = full_name
        if email is not None:
            user.email = email
        return user

    async def update_password_hash(self, user_id: str | uuid.UUID, password_hash: str) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError()
        user.password_hash = password_hash
        return user


def _make_user(*, email: str = "user@example.com", password: str = "Password1!") -> User:
    return User(
        tenant_id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
    )


class TestGetProfile:
    async def test_returns_user_when_found(self) -> None:
        user = _make_user()
        repo = FakeUserRepo([user])
        service = UserService(repo)

        assert await service.get_profile(str(user.id)) is user

    async def test_raises_when_missing(self) -> None:
        service = UserService(FakeUserRepo())

        with pytest.raises(UserNotFoundError):
            await service.get_profile(uuid.uuid4())


class TestUpdateProfile:
    async def test_delegates_to_repo(self) -> None:
        user = _make_user()
        repo = FakeUserRepo([user])
        service = UserService(repo)

        updated = await service.update_profile(
            str(user.id), UserUpdateRequest(full_name="New Name")
        )

        assert updated.full_name == "New Name"
        assert updated is user


class TestChangePassword:
    async def test_updates_hash_when_current_password_is_correct(self) -> None:
        user = _make_user(password="OldPass1!")
        repo = FakeUserRepo([user])
        service = UserService(repo)

        await service.change_password(str(user.id), "OldPass1!", "NewPass1!")

        assert verify_password("NewPass1!", user.password_hash)

    async def test_raises_when_current_password_is_wrong(self) -> None:
        user = _make_user(password="OldPass1!")
        repo = FakeUserRepo([user])
        service = UserService(repo)

        with pytest.raises(InvalidPasswordError):
            await service.change_password(str(user.id), "WrongPass1!", "NewPass1!")

        assert verify_password("OldPass1!", user.password_hash)
