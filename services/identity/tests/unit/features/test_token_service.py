"""Unit tests for the auth feature TokenService (fake SessionRepositoryPort)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_jwt,
)
from identity.domain.entities import Session, SessionStatus
from identity.features.auth.service import TokenService
from skyrict_common.exceptions import TokenInvalidError, TokenReuseDetectedError

USER_ID = str(uuid.uuid4())
TENANT_ID = str(uuid.uuid4())


class FakeSessionRepo:
    """Minimal in-memory SessionRepositoryPort double for token flow tests."""

    def __init__(self, sessions: list[Session] | None = None) -> None:
        self.sessions: dict[uuid.UUID, Session] = {}
        for session in sessions or []:
            assert session.id is not None
            self.sessions[session.id] = session
        self.revoked: list[uuid.UUID] = []
        self.revoked_for_users: list[uuid.UUID] = []
        self.rotations: list[tuple[uuid.UUID, str]] = []

    async def get_by_id(self, session_id: str | uuid.UUID) -> Session | None:
        return self.sessions.get(uuid.UUID(str(session_id)))

    async def create(self, session: Session) -> Session:
        if session.id is None:
            session.id = uuid.uuid4()
        self.sessions[session.id] = session
        return session

    async def get_active_by_user(self, user_id: str | uuid.UUID) -> list[Session]:
        return [
            session
            for session in self.sessions.values()
            if session.user_id == uuid.UUID(str(user_id)) and session.is_active
        ]

    async def revoke_session(self, session_id: str | uuid.UUID) -> None:
        self.revoked.append(uuid.UUID(str(session_id)))
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.status = SessionStatus.REVOKED

    async def revoke_all_for_user(self, user_id: str | uuid.UUID) -> None:
        self.revoked_for_users.append(uuid.UUID(str(user_id)))
        for session in self.sessions.values():
            if session.user_id == uuid.UUID(str(user_id)):
                session.status = SessionStatus.REVOKED

    async def rotate(
        self,
        session_id: str | uuid.UUID,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> None:
        self.rotations.append((uuid.UUID(str(session_id)), refresh_token_hash))
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.refresh_token_hash = refresh_token_hash
            session.expires_at = expires_at

    async def commit(self) -> None:
        return None


class FakeAuditService:
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
        tenant_id: str | None = None,
    ) -> None:
        self.events.append(
            {"action": action, "target": target, "user_id": user_id, "tenant_id": tenant_id}
        )


def _bound_session(token: str) -> Session:
    payload = verify_jwt(token)
    return Session(
        id=uuid.UUID(payload["session_id"]),
        user_id=uuid.UUID(USER_ID),
        tenant_id=uuid.UUID(TENANT_ID),
        refresh_token_hash=hash_refresh_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )


class TestCreateTokenPair:
    async def test_returns_pair_with_access_and_refresh_tokens(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())

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

    async def test_refresh_token_carries_session_id_claim(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())
        session_id = str(uuid.uuid4())

        pair = await service.create_token_pair(
            user_id=USER_ID, tenant_id=TENANT_ID, session_id=session_id
        )

        assert verify_jwt(pair.refresh_token)["session_id"] == session_id


class TestRefreshTokens:
    async def test_rotates_hash_and_returns_new_pair(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        session.expires_at = datetime.now(UTC) + timedelta(days=1)
        original_expires_at = session.expires_at
        repo = FakeSessionRepo([session])
        service = TokenService(repo, FakeAuditService())

        pair = await service.refresh_tokens(token)

        assert pair.access_token
        assert pair.refresh_token != token
        session_id = uuid.UUID(verify_jwt(token)["session_id"])
        assert repo.rotations == [(session_id, hash_refresh_token(pair.refresh_token))]
        assert repo.sessions[session_id].refresh_token_hash == hash_refresh_token(
            pair.refresh_token
        )
        assert repo.sessions[session_id].expires_at > original_expires_at

    async def test_old_token_after_rotation_triggers_reuse_chain_kill(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        repo = FakeSessionRepo([session])
        audit = FakeAuditService()
        service = TokenService(repo, audit)

        await service.refresh_tokens(token)

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

        assert repo.revoked_for_users == [uuid.UUID(USER_ID)]
        assert repo.sessions[session.id].is_active is False
        assert audit.events[-1]["action"] == "auth.refresh.reuse_detected"

    async def test_reuse_when_session_missing(self) -> None:
        token, _ = uuid_token_and_session()
        repo = FakeSessionRepo()
        audit = FakeAuditService()
        service = TokenService(repo, audit)

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

        assert repo.revoked_for_users == [uuid.UUID(USER_ID)]
        assert audit.events[-1]["action"] == "auth.refresh.reuse_detected"

    async def test_reuse_when_session_revoked(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        session.status = SessionStatus.REVOKED
        repo = FakeSessionRepo([session])
        service = TokenService(repo, FakeAuditService())

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

    async def test_reuse_when_session_expired(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        repo = FakeSessionRepo([session])
        service = TokenService(repo, FakeAuditService())

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

    async def test_rejects_access_token(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens(access)

    async def test_rejects_garbage_token(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens("not-a-jwt")


class TestRevokeToken:
    async def test_revokes_only_the_matching_session(self) -> None:
        token_a = _bound_token()
        token_b = _bound_token()
        session_a = _bound_session(token_a)
        session_b = _bound_session(token_b)
        repo = FakeSessionRepo([session_a, session_b])
        service = TokenService(repo, FakeAuditService())

        await service.revoke_token(token_a)

        assert repo.revoked == [session_a.id]
        assert session_b.is_active is True

    async def test_revokes_nothing_for_a_foreign_session(self) -> None:
        token = _bound_token()
        session = _bound_session(token)
        session.user_id = uuid.uuid4()
        repo = FakeSessionRepo([session])
        service = TokenService(repo, FakeAuditService())

        await service.revoke_token(token)

        assert repo.revoked == []

    async def test_rejects_access_token(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.revoke_token(access)


class TestIntrospect:
    async def test_active_for_valid_access_token(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        result = await service.introspect(access)

        assert result["active"] is True
        assert result["sub"] == USER_ID
        assert result["tenant_id"] == TENANT_ID
        assert result["type"] == "access"
        assert result["exp"] is not None

    async def test_inactive_for_garbage_token(self) -> None:
        service = TokenService(FakeSessionRepo(), FakeAuditService())

        result = await service.introspect("garbage")

        assert result == {"active": False}


def uuid_token_and_session() -> tuple[str, str]:
    session_id = str(uuid.uuid4())
    return (
        create_refresh_token(USER_ID, tenant_id=TENANT_ID, session_id=session_id),
        session_id,
    )


def _bound_token() -> str:
    token, _ = uuid_token_and_session()
    return token
