"""Unit tests for the auth feature AuthenticationService (fake ports)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.security import hash_password
from identity.core.tenant_context import TenantContext
from identity.domain.entities import User
from identity.domain.value_objects import TokenPair
from identity.features.auth.schemas import LoginRequest, RegisterRequest
from identity.features.auth.service import AuthenticationService
from skyrict_common.exceptions import (
    InvalidPasswordError,
    UserAlreadyExistsError,
    UserDisabledError,
    UserNotFoundError,
)


class FakeUserRepo:
    """In-memory UserRepositoryPort double (subset used by auth flows)."""

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


class FakeTokenService:
    """TokenService double — returns a fixed TokenPair, records call args."""

    def __init__(self) -> None:
        self.pairs_created: list[tuple[str, str]] = []

    async def create_token_pair(self, *, user_id: str, tenant_id: str) -> TokenPair:
        self.pairs_created.append((user_id, tenant_id))
        return TokenPair(access_token="access-token", refresh_token="refresh-token")


class FakeAuditService:
    """AuditService double — records log() calls."""

    def __init__(self) -> None:
        self.events: list[dict[str, str | None]] = []

    async def log(
        self,
        *,
        action: str,
        target: str,
        user_id: str | None = None,
        details: dict[str, object] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.events.append({"action": action, "target": target, "user_id": user_id})


@pytest.fixture
def tenant_ctx() -> str:
    tenant_id = str(uuid.uuid4())
    TenantContext.set(tenant_id)
    yield tenant_id
    TenantContext.reset()


def _make_service(
    users: list[User] | None = None,
) -> tuple[AuthenticationService, FakeUserRepo, FakeTokenService, FakeAuditService]:
    user_repo = FakeUserRepo(users)
    token_svc = FakeTokenService()
    audit_svc = FakeAuditService()
    service = AuthenticationService(user_repo, _NoopTenantRepo(), token_svc, audit_svc)
    return service, user_repo, token_svc, audit_svc


class _NoopTenantRepo:
    """TenantRepositoryPort double — the auth flows under test never query it."""

    async def get_by_id(self, tenant_id: str | uuid.UUID):
        return None

    async def get_by_slug(self, slug: str):
        return None

    async def slug_exists(self, slug: str) -> bool:
        return False

    async def create(self, tenant):
        return tenant


def _make_user(
    *,
    email: str = "user@example.com",
    password: str = "Password1!",
    is_active: bool = True,
) -> User:
    return User(
        tenant_id=uuid.UUID(TenantContext.get()),
        email=email,
        password_hash=hash_password(password),
        full_name="Test User",
        is_active=is_active,
    )


class TestLogin:
    async def test_success_returns_tokens_and_user(self, tenant_ctx: str) -> None:
        user = _make_user()
        service, _, token_svc, audit_svc = _make_service([user])

        result = await service.login(LoginRequest(email=user.email, password="Password1!"))

        assert result["access_token"] == "access-token"
        assert result["refresh_token"] == "refresh-token"
        assert result["token_type"] == "Bearer"
        assert result["user"] is user
        assert token_svc.pairs_created == [(str(user.id), tenant_ctx)]
        assert audit_svc.events == [
            {"action": "auth.login.success", "target": f"user:{user.id}", "user_id": str(user.id)}
        ]

    async def test_unknown_email_raises(self, tenant_ctx: str) -> None:
        service, _, token_svc, audit_svc = _make_service([])

        with pytest.raises(UserNotFoundError):
            await service.login(LoginRequest(email="nobody@example.com", password="Password1!"))

        assert token_svc.pairs_created == []
        assert audit_svc.events == []

    async def test_disabled_user_raises(self, tenant_ctx: str) -> None:
        user = _make_user(is_active=False)
        service, _, token_svc, audit_svc = _make_service([user])

        with pytest.raises(UserDisabledError):
            await service.login(LoginRequest(email=user.email, password="Password1!"))

        assert token_svc.pairs_created == []
        assert audit_svc.events == []

    async def test_wrong_password_raises(self, tenant_ctx: str) -> None:
        user = _make_user()
        service, _, token_svc, audit_svc = _make_service([user])

        with pytest.raises(InvalidPasswordError):
            await service.login(LoginRequest(email=user.email, password="WrongPass1!"))

        assert token_svc.pairs_created == []
        assert audit_svc.events == []


class TestRegister:
    async def test_creates_user_and_returns_tokens(self, tenant_ctx: str) -> None:
        service, user_repo, token_svc, audit_svc = _make_service([])

        result = await service.register(
            RegisterRequest(email="new@example.com", password="Password1!", full_name="New User")
        )

        assert len(user_repo.created) == 1
        user = user_repo.created[0]
        assert user.email == "new@example.com"
        assert user.full_name == "New User"
        assert user.is_active is True
        assert user.is_verified is False
        assert str(user.tenant_id) == tenant_ctx
        assert result["user"] is user
        assert result["access_token"] == "access-token"
        assert token_svc.pairs_created == [(str(user.id), tenant_ctx)]
        assert audit_svc.events == [
            {
                "action": "auth.register.success",
                "target": f"user:{user.id}",
                "user_id": str(user.id),
            }
        ]

    async def test_duplicate_email_raises(self, tenant_ctx: str) -> None:
        user = _make_user(email="taken@example.com")
        service, user_repo, token_svc, audit_svc = _make_service([user])

        with pytest.raises(UserAlreadyExistsError):
            await service.register(
                RegisterRequest(email="taken@example.com", password="Password1!", full_name="Dup")
            )

        assert user_repo.created == []
        assert token_svc.pairs_created == []
        assert audit_svc.events == []
