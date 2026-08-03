"""Unit tests for the sessions feature service (fake SessionRepositoryPort)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.domain.entities import Session
from identity.features.sessions.service import SessionService
from skyrict_common.exceptions import SessionNotFoundError


class FakeSessionRepo:
    """In-memory SessionRepositoryPort double."""

    def __init__(self, sessions: list[Session] | None = None) -> None:
        self.sessions: dict[uuid.UUID, Session] = {}
        for session in sessions or []:
            if session.id is None:
                session.id = uuid.uuid4()
            self.sessions[session.id] = session
        self.revoked: list[uuid.UUID] = []
        self.revoked_for_users: list[uuid.UUID] = []

    async def get_by_id(self, session_id: str | uuid.UUID) -> Session | None:
        return self.sessions.get(uuid.UUID(str(session_id)))

    async def create(self, session: Session) -> Session:
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

    async def revoke_all_for_user(self, user_id: str | uuid.UUID) -> None:
        self.revoked_for_users.append(uuid.UUID(str(user_id)))


class TestCreateSession:
    async def test_builds_active_session_with_default_ttl(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo)
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        before = datetime.now(UTC)

        session = await service.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash="hashed-token",
            user_agent="pytest-agent",
            ip_address="127.0.0.1",
        )

        assert session.id is not None
        assert session.user_id == user_id
        assert session.tenant_id == tenant_id
        assert session.refresh_token_hash == "hashed-token"
        assert session.user_agent == "pytest-agent"
        assert session.ip_address == "127.0.0.1"
        assert session.is_active is True
        assert session.created_at >= before
        assert abs((session.last_active_at - session.created_at).total_seconds()) < 1
        ttl = session.expires_at - session.created_at
        assert abs((ttl - timedelta(days=7)).total_seconds()) < 1


class TestListUserSessions:
    async def test_returns_active_sessions(self) -> None:
        user_id = uuid.uuid4()
        active = Session(user_id=user_id, tenant_id=uuid.uuid4(), refresh_token_hash="a")
        inactive = Session(
            user_id=user_id, tenant_id=uuid.uuid4(), refresh_token_hash="b", is_active=False
        )
        repo = FakeSessionRepo([active, inactive])
        service = SessionService(repo)

        sessions = await service.list_user_sessions(str(user_id))

        assert sessions == [active]


class TestRevokeSession:
    async def test_revokes_when_found(self) -> None:
        session = Session(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), refresh_token_hash="a")
        repo = FakeSessionRepo([session])
        service = SessionService(repo)

        await service.revoke_session(str(session.id))

        assert repo.revoked == [session.id]

    async def test_raises_when_missing(self) -> None:
        service = SessionService(FakeSessionRepo())

        with pytest.raises(SessionNotFoundError):
            await service.revoke_session(uuid.uuid4())


class TestRevokeAllSessions:
    async def test_delegates_to_repo(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo)
        user_id = uuid.uuid4()

        await service.revoke_all_sessions(str(user_id))

        assert repo.revoked_for_users == [user_id]
