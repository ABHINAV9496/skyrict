"""Unit tests for the sessions feature service (fake SessionRepositoryPort)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.core.config import settings
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
            session.is_active = False

    async def revoke_all_for_user(self, user_id: str | uuid.UUID) -> None:
        self.revoked_for_users.append(uuid.UUID(str(user_id)))

    async def rotate(
        self,
        session_id: str | uuid.UUID,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> None:
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.refresh_token_hash = refresh_token_hash
            session.expires_at = expires_at


class TestCreateSession:
    async def test_builds_active_session_with_sliding_ttl(self) -> None:
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
        assert abs((ttl - timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)).total_seconds()) < 1

    async def test_persists_a_pre_generated_id(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo)
        session_id, user_id, tenant_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        session = await service.create_session(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash="h",
        )

        assert session.id == session_id


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


class TestHasPriorDevice:
    def _make_session(self, user_id: uuid.UUID, *, user_agent: str, ip_address: str) -> Session:
        return Session(
            user_id=user_id,
            tenant_id=uuid.uuid4(),
            refresh_token_hash="h",
            user_agent=user_agent,
            ip_address=ip_address,
        )

    async def test_true_when_same_device_and_subnet(self) -> None:
        user_id = uuid.uuid4()
        repo = FakeSessionRepo(
            [self._make_session(user_id, user_agent="Mozilla/5.0 (X11)", ip_address="203.0.113.7")]
        )
        service = SessionService(repo)

        assert (
            await service.has_prior_device(
                user_id, user_agent="  Mozilla/5.0 (x11)  ", ip_address="203.0.113.99"
            )
            is True
        )

    async def test_false_for_different_user_agent(self) -> None:
        user_id = uuid.uuid4()
        repo = FakeSessionRepo(
            [self._make_session(user_id, user_agent="Mozilla/5.0", ip_address="203.0.113.7")]
        )
        service = SessionService(repo)

        assert (
            await service.has_prior_device(user_id, user_agent="curl/8.0", ip_address="203.0.113.7")
            is False
        )

    async def test_false_for_different_subnet(self) -> None:
        user_id = uuid.uuid4()
        repo = FakeSessionRepo(
            [self._make_session(user_id, user_agent="Mozilla/5.0", ip_address="203.0.113.7")]
        )
        service = SessionService(repo)

        assert (
            await service.has_prior_device(
                user_id, user_agent="Mozilla/5.0", ip_address="198.51.100.7"
            )
            is False
        )


class TestRevokeSession:
    async def test_revokes_owned_session(self) -> None:
        user_id = uuid.uuid4()
        session = Session(user_id=user_id, tenant_id=uuid.uuid4(), refresh_token_hash="a")
        repo = FakeSessionRepo([session])
        service = SessionService(repo)

        await service.revoke_session(user_id, session.id)

        assert repo.revoked == [session.id]

    async def test_raises_for_missing_session(self) -> None:
        service = SessionService(FakeSessionRepo())

        with pytest.raises(SessionNotFoundError):
            await service.revoke_session(uuid.uuid4(), uuid.uuid4())

    async def test_raises_for_foreign_session(self) -> None:
        session = Session(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), refresh_token_hash="a")
        repo = FakeSessionRepo([session])
        service = SessionService(repo)

        with pytest.raises(SessionNotFoundError):
            await service.revoke_session(uuid.uuid4(), session.id)

        assert repo.revoked == []


class TestRevokeAllSessions:
    async def test_delegates_to_repo(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo)
        user_id = uuid.uuid4()

        await service.revoke_all_sessions(str(user_id))

        assert repo.revoked_for_users == [user_id]
