"""Unit tests for the auth feature TokenService (fake SessionRepositoryPort)."""

from __future__ import annotations

import uuid

import pytest

from identity.core.security import create_access_token, create_refresh_token, verify_jwt
from identity.domain.entities import Session
from identity.features.auth.service import TokenService
from skyrict_common.exceptions import TokenInvalidError


class FakeSessionRepo:
    """Minimal in-memory SessionRepositoryPort double for token flow tests."""

    def __init__(self, active: bool = True) -> None:
        self.active = active
        self.revoked_for_users: list[uuid.UUID] = []

    async def get_by_id(self, session_id: str | uuid.UUID) -> Session | None:
        return None

    async def create(self, session: Session) -> Session:
        return session

    async def get_active_by_user(self, user_id: str | uuid.UUID) -> list[Session]:
        if not self.active:
            return []
        return [
            Session(user_id=uuid.UUID(str(user_id)), tenant_id=uuid.uuid4(), refresh_token_hash="h")
        ]

    async def revoke_session(self, session_id: str | uuid.UUID) -> None:
        return None

    async def revoke_all_for_user(self, user_id: str | uuid.UUID) -> None:
        self.revoked_for_users.append(uuid.UUID(str(user_id)))


USER_ID = str(uuid.uuid4())
TENANT_ID = str(uuid.uuid4())


class TestCreateTokenPair:
    async def test_returns_pair_with_access_and_refresh_tokens(self) -> None:
        service = TokenService(FakeSessionRepo())

        pair = await service.create_token_pair(user_id=USER_ID, tenant_id=TENANT_ID)

        assert pair.access_token
        assert pair.refresh_token
        assert pair.token_type == "Bearer"
        assert pair.expires_in > 0
        access_claims = verify_jwt(pair.access_token)
        refresh_claims = verify_jwt(pair.refresh_token)
        assert access_claims["type"] == "access"
        assert refresh_claims["type"] == "refresh"
        assert access_claims["sub"] == USER_ID
        assert access_claims["tenant_id"] == TENANT_ID


class TestRefreshTokens:
    async def test_issues_new_pair_for_active_session(self) -> None:
        service = TokenService(FakeSessionRepo(active=True))
        refresh = create_refresh_token(USER_ID, tenant_id=TENANT_ID)

        pair = await service.refresh_tokens(refresh)

        assert pair.access_token
        assert verify_jwt(pair.access_token)["sub"] == USER_ID

    async def test_rejects_access_token(self) -> None:
        service = TokenService(FakeSessionRepo(active=True))
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens(access)

    async def test_rejects_when_no_active_session(self) -> None:
        service = TokenService(FakeSessionRepo(active=False))
        refresh = create_refresh_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens(refresh)

    async def test_rejects_garbage_token(self) -> None:
        service = TokenService(FakeSessionRepo(active=True))

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens("not-a-jwt")


class TestRevokeToken:
    async def test_revokes_all_sessions_for_refresh_token_subject(self) -> None:
        repo = FakeSessionRepo(active=True)
        service = TokenService(repo)
        refresh = create_refresh_token(USER_ID, tenant_id=TENANT_ID)

        await service.revoke_token(refresh)

        assert repo.revoked_for_users == [uuid.UUID(USER_ID)]

    async def test_rejects_access_token(self) -> None:
        service = TokenService(FakeSessionRepo(active=True))
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.revoke_token(access)


class TestIntrospect:
    async def test_active_for_valid_access_token(self) -> None:
        service = TokenService(FakeSessionRepo(active=True))
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        result = await service.introspect(access)

        assert result["active"] is True
        assert result["sub"] == USER_ID
        assert result["tenant_id"] == TENANT_ID
        assert result["type"] == "access"
        assert result["exp"] is not None

    async def test_inactive_for_garbage_token(self) -> None:
        service = TokenService(FakeSessionRepo(active=True))

        result = await service.introspect("garbage")

        assert result == {"active": False}
