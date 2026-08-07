"""Unit tests for the auth feature TokenService (fake SessionService)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.core.audit_events import AUTH_REFRESH_REUSE_DETECTED, AUTH_REFRESH_SUCCESS
from identity.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_jwt,
)
from identity.domain.entities import Session, SessionStatus
from identity.features.auth.service import TokenService
from skyrict_common.exceptions import (
    SessionNotFoundError,
    TokenExpiredError,
    TokenInvalidError,
    TokenReuseDetectedError,
)

USER_ID = str(uuid.uuid4())
TENANT_ID = str(uuid.uuid4())


class FakeSessionService:
    """In-memory SessionService double for token flow tests."""

    def __init__(self, sessions: list[Session] | None = None) -> None:
        self.sessions: dict[uuid.UUID, Session] = {}
        for session in sessions or []:
            assert session.id is not None
            self.sessions[session.id] = session
        self.revoked: list[uuid.UUID] = []
        self.revoked_for_users: list[uuid.UUID] = []
        self.revoked_families: list[uuid.UUID] = []
        self.expired: list[uuid.UUID] = []
        self.rotations: list[tuple[uuid.UUID, str]] = []
        self.committed = False

    async def get_session(self, session_id: str | uuid.UUID) -> Session | None:
        return self.sessions.get(uuid.UUID(str(session_id)))

    async def rotate_session(
        self,
        session_id: str | uuid.UUID,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> Session | None:
        self.rotations.append((uuid.UUID(str(session_id)), refresh_token_hash))
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.refresh_token_hash = refresh_token_hash
            session.expires_at = expires_at
        return session

    async def expire_session(self, session_id: str | uuid.UUID) -> Session | None:
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            self.expired.append(uuid.UUID(str(session_id)))
            session.status = SessionStatus.EXPIRED
            session.expired_at = datetime.now(UTC)
        return session

    async def revoke_session(self, user_id: str | uuid.UUID, session_id: str | uuid.UUID) -> None:
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if (
            session is None
            or session.user_id != uuid.UUID(str(user_id))
            or session.status is not SessionStatus.ACTIVE
        ):
            raise SessionNotFoundError()
        self.revoked.append(uuid.UUID(str(session_id)))
        session.status = SessionStatus.REVOKED
        session.revoked_at = datetime.now(UTC)

    async def revoke_all_sessions(self, user_id: str | uuid.UUID) -> None:
        self.revoked_for_users.append(uuid.UUID(str(user_id)))
        for session in self.sessions.values():
            if session.user_id == uuid.UUID(str(user_id)):
                session.status = SessionStatus.REVOKED

    async def revoke_family(self, family_id: str | uuid.UUID) -> None:
        self.revoked_families.append(uuid.UUID(str(family_id)))
        for session in self.sessions.values():
            if session.token_family_id == uuid.UUID(str(family_id)):
                session.status = SessionStatus.REVOKED

    async def commit(self) -> None:
        self.committed = True


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


def _bound_session(token: str, *, family_id: uuid.UUID | None = None) -> Session:
    payload = verify_jwt(token)
    return Session(
        id=uuid.UUID(payload["session_id"]),
        user_id=uuid.UUID(USER_ID),
        tenant_id=uuid.UUID(TENANT_ID),
        refresh_token_hash=hash_refresh_token(token),
        token_family_id=family_id or uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )


class TestCreateTokenPair:
    async def test_returns_pair_with_access_and_refresh_tokens(self) -> None:
        service = TokenService(FakeSessionService(), FakeAuditService())

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
        service = TokenService(FakeSessionService(), FakeAuditService())
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
        service = TokenService(FakeSessionService([session]), FakeAuditService())

        pair = await service.refresh_tokens(token)

        assert pair.access_token
        assert pair.refresh_token != token
        session_id = uuid.UUID(verify_jwt(token)["session_id"])
        assert service.session_service.rotations == [
            (session_id, hash_refresh_token(pair.refresh_token))
        ]
        assert service.session_service.sessions[session_id].refresh_token_hash == (
            hash_refresh_token(pair.refresh_token)
        )
        assert service.session_service.sessions[session_id].expires_at > original_expires_at

    async def test_rotation_preserves_token_family(self) -> None:
        token, _ = uuid_token_and_session()
        family_id = uuid.uuid4()
        session = _bound_session(token, family_id=family_id)
        service = TokenService(FakeSessionService([session]), FakeAuditService())

        await service.refresh_tokens(token)

        session_id = uuid.UUID(verify_jwt(token)["session_id"])
        assert service.session_service.sessions[session_id].token_family_id == family_id

    async def test_old_token_after_rotation_triggers_family_chain_kill(self) -> None:
        token, _ = uuid_token_and_session()
        family_id = uuid.uuid4()
        session = _bound_session(token, family_id=family_id)
        sibling = Session(
            id=uuid.uuid4(),
            user_id=uuid.UUID(USER_ID),
            tenant_id=uuid.UUID(TENANT_ID),
            refresh_token_hash="other",
            token_family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        session_service = FakeSessionService([session, sibling])
        audit = FakeAuditService()
        service = TokenService(session_service, audit)

        await service.refresh_tokens(token)

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

        assert session_service.revoked_families == [family_id]
        assert session.status is SessionStatus.REVOKED
        assert sibling.status is SessionStatus.REVOKED
        assert audit.events[-1]["action"] == AUTH_REFRESH_REUSE_DETECTED
        assert audit.events[-1]["target"] == f"session:{session.id}"
        assert session_service.committed is True

    async def test_reuse_when_session_missing_falls_back_to_all_user_revoke(self) -> None:
        token, _ = uuid_token_and_session()
        session_service = FakeSessionService()
        audit = FakeAuditService()
        service = TokenService(session_service, audit)

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

        assert session_service.revoked_for_users == [uuid.UUID(USER_ID)]
        assert session_service.revoked_families == []
        assert audit.events[-1]["action"] == AUTH_REFRESH_REUSE_DETECTED

    async def test_reuse_when_session_revoked(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        session.status = SessionStatus.REVOKED
        session_service = FakeSessionService([session])
        service = TokenService(session_service, FakeAuditService())

        with pytest.raises(TokenReuseDetectedError):
            await service.refresh_tokens(token)

    async def test_expired_session_is_marked_expired_and_rejected(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session_service = FakeSessionService([session])
        service = TokenService(session_service, FakeAuditService())

        with pytest.raises(TokenExpiredError):
            await service.refresh_tokens(token)

        assert session_service.expired == [session.id]
        assert session.status is SessionStatus.EXPIRED
        assert session_service.revoked_families == []

    async def test_refresh_emits_success_audit(self) -> None:
        token, _ = uuid_token_and_session()
        session = _bound_session(token)
        audit = FakeAuditService()
        service = TokenService(FakeSessionService([session]), audit)

        await service.refresh_tokens(token)

        assert audit.events[-1]["action"] == AUTH_REFRESH_SUCCESS
        assert audit.events[-1]["target"] == f"session:{session.id}"

    async def test_rejects_access_token(self) -> None:
        service = TokenService(FakeSessionService(), FakeAuditService())
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens(access)

    async def test_rejects_garbage_token(self) -> None:
        service = TokenService(FakeSessionService(), FakeAuditService())

        with pytest.raises(TokenInvalidError):
            await service.refresh_tokens("not-a-jwt")


class TestRevokeToken:
    async def test_revokes_only_the_matching_session(self) -> None:
        token_a = _bound_token()
        token_b = _bound_token()
        session_a = _bound_session(token_a)
        session_b = _bound_session(token_b)
        session_service = FakeSessionService([session_a, session_b])
        service = TokenService(session_service, FakeAuditService())

        await service.revoke_token(token_a)

        assert session_service.revoked == [session_a.id]
        assert session_b.status is SessionStatus.ACTIVE

    async def test_revokes_nothing_for_a_foreign_session(self) -> None:
        token = _bound_token()
        session = _bound_session(token)
        session.user_id = uuid.uuid4()
        session_service = FakeSessionService([session])
        service = TokenService(session_service, FakeAuditService())

        await service.revoke_token(token)

        assert session_service.revoked == []

    async def test_logout_is_idempotent_for_an_already_revoked_session(self) -> None:
        token = _bound_token()
        session = _bound_session(token)
        session.status = SessionStatus.REVOKED
        session_service = FakeSessionService([session])
        service = TokenService(session_service, FakeAuditService())

        await service.revoke_token(token)

        assert session_service.revoked == []

    async def test_rejects_access_token(self) -> None:
        service = TokenService(FakeSessionService(), FakeAuditService())
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        with pytest.raises(TokenInvalidError):
            await service.revoke_token(access)


class TestIntrospect:
    async def test_active_for_valid_access_token(self) -> None:
        service = TokenService(FakeSessionService(), FakeAuditService())
        access = create_access_token(USER_ID, tenant_id=TENANT_ID)

        result = await service.introspect(access)

        assert result["active"] is True
        assert result["sub"] == USER_ID
        assert result["tenant_id"] == TENANT_ID
        assert result["type"] == "access"
        assert result["exp"] is not None

    async def test_inactive_for_garbage_token(self) -> None:
        service = TokenService(FakeSessionService(), FakeAuditService())

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
