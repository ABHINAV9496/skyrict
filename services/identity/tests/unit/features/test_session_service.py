"""Unit tests for the sessions feature service (fake SessionRepositoryPort)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from identity.core.audit_events import (
    SESSION_CREATED,
    SESSION_REVOKED,
    SESSION_REVOKED_ALL,
    SESSION_TRUSTED,
)
from identity.core.config import settings
from identity.domain.entities import Session, SessionStatus
from identity.features.sessions.service import SessionService
from skyrict_common.exceptions import SessionNotFoundError


class FakeAuditService:
    """In-memory AuditService double capturing recorded entries."""

    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    async def log(self, *, action: str, target: str, **kwargs: object) -> None:
        self.entries.append({"action": action, "target": target, **kwargs})


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
        self.revoked_families: list[uuid.UUID] = []
        self.expired: list[uuid.UUID] = []
        self.committed = False

    async def get_by_id(self, session_id: str | uuid.UUID) -> Session | None:
        return self.sessions.get(uuid.UUID(str(session_id)))

    async def create(self, session: Session) -> Session:
        if session.id is None:
            session.id = uuid.uuid4()
        self.sessions[session.id] = session
        return session

    async def get_active_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> list[Session]:
        now = datetime.now(UTC)
        return sorted(
            (
                session
                for session in self.sessions.values()
                if session.user_id == uuid.UUID(str(user_id))
                and (tenant_id is None or session.tenant_id == uuid.UUID(str(tenant_id)))
                and session.status is SessionStatus.ACTIVE
                and session.expires_at > now
            ),
            key=lambda s: s.created_at,
            reverse=True,
        )

    async def get_active_by_family(self, family_id: str | uuid.UUID) -> list[Session]:
        now = datetime.now(UTC)
        return [
            session
            for session in self.sessions.values()
            if session.token_family_id == uuid.UUID(str(family_id))
            and session.status is SessionStatus.ACTIVE
            and session.expires_at > now
        ]

    async def revoke_session(self, session_id: str | uuid.UUID) -> None:
        self.revoked.append(uuid.UUID(str(session_id)))
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.status = SessionStatus.REVOKED
            session.revoked_at = datetime.now(UTC)

    async def revoke_all_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> None:
        self.revoked_for_users.append(uuid.UUID(str(user_id)))
        for session in self.sessions.values():
            if session.user_id == uuid.UUID(str(user_id)) and (
                tenant_id is None or session.tenant_id == uuid.UUID(str(tenant_id))
            ):
                session.status = SessionStatus.REVOKED

    async def revoke_family(self, family_id: str | uuid.UUID) -> None:
        self.revoked_families.append(uuid.UUID(str(family_id)))
        for session in self.sessions.values():
            if session.token_family_id == uuid.UUID(str(family_id)):
                session.status = SessionStatus.REVOKED

    async def set_trusted(self, session_id: str | uuid.UUID, is_trusted: bool) -> None:
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.is_trusted = is_trusted

    async def mark_expired(self, session_id: str | uuid.UUID) -> None:
        self.expired.append(uuid.UUID(str(session_id)))
        session = self.sessions.get(uuid.UUID(str(session_id)))
        if session is not None:
            session.status = SessionStatus.EXPIRED
            session.expired_at = datetime.now(UTC)

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

    async def commit(self) -> None:
        self.committed = True


def _service(repo: FakeSessionRepo | None = None, audit: FakeAuditService | None = None):
    return SessionService(repo or FakeSessionRepo(), audit or FakeAuditService())


def _active_session(
    user_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None = None,
    family_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> Session:
    return Session(
        user_id=user_id,
        tenant_id=tenant_id or uuid.uuid4(),
        refresh_token_hash="h",
        token_family_id=family_id or uuid.uuid4(),
        expires_at=expires_at or datetime.now(UTC) + timedelta(days=1),
    )


class TestCreateSession:
    async def test_builds_active_session_with_sliding_ttl(self) -> None:
        repo = FakeSessionRepo()
        audit = FakeAuditService()
        service = SessionService(repo, audit)
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
        assert session.status is SessionStatus.ACTIVE
        assert session.is_active is True
        assert session.token_family_id is not None
        assert session.created_at >= before
        assert abs((session.last_active_at - session.created_at).total_seconds()) < 1
        ttl = session.expires_at - session.created_at
        assert abs((ttl - timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)).total_seconds()) < 1

    async def test_audits_session_created(self) -> None:
        repo = FakeSessionRepo()
        audit = FakeAuditService()
        service = SessionService(repo, audit)
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()

        session = await service.create_session(
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash="hashed-token",
            ip_address="127.0.0.1",
        )

        assert audit.entries[0]["action"] == SESSION_CREATED
        assert audit.entries[0]["target"] == f"session:{session.id}"
        assert audit.entries[0]["user_id"] == str(user_id)
        assert audit.entries[0]["tenant_id"] == str(tenant_id)

    async def test_persists_a_pre_generated_id(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo, FakeAuditService())
        session_id, user_id, tenant_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        session = await service.create_session(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash="h",
        )

        assert session.id == session_id

    async def test_uses_provided_token_family(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo, FakeAuditService())
        family_id = uuid.uuid4()

        session = await service.create_session(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            refresh_token_hash="h",
            token_family_id=family_id,
        )

        assert session.token_family_id == family_id


class TestListUserSessions:
    async def test_returns_only_active_unexpired_sessions(self) -> None:
        user_id = uuid.uuid4()
        active = _active_session(user_id)
        revoked = _active_session(user_id)
        revoked.status = SessionStatus.REVOKED
        expired = _active_session(user_id, expires_at=datetime.now(UTC) - timedelta(hours=1))
        repo = FakeSessionRepo([active, revoked, expired])
        service = SessionService(repo, FakeAuditService())

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
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )

    async def test_true_when_same_device_and_subnet(self) -> None:
        user_id = uuid.uuid4()
        repo = FakeSessionRepo(
            [self._make_session(user_id, user_agent="Mozilla/5.0 (X11)", ip_address="203.0.113.7")]
        )
        service = SessionService(repo, FakeAuditService())

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
        service = SessionService(repo, FakeAuditService())

        assert (
            await service.has_prior_device(user_id, user_agent="curl/8.0", ip_address="203.0.113.7")
            is False
        )

    async def test_false_for_different_subnet(self) -> None:
        user_id = uuid.uuid4()
        repo = FakeSessionRepo(
            [self._make_session(user_id, user_agent="Mozilla/5.0", ip_address="203.0.113.7")]
        )
        service = SessionService(repo, FakeAuditService())

        assert (
            await service.has_prior_device(
                user_id, user_agent="Mozilla/5.0", ip_address="198.51.100.7"
            )
            is False
        )


class TestRevokeSession:
    async def test_revokes_owned_session(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())

        await service.revoke_session(user_id, session.id)

        assert repo.revoked == [session.id]
        assert session.status is SessionStatus.REVOKED

    async def test_audits_session_revoked(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        repo = FakeSessionRepo([session])
        audit = FakeAuditService()
        service = SessionService(repo, audit)

        await service.revoke_session(user_id, session.id)

        assert audit.entries[0]["action"] == SESSION_REVOKED
        assert audit.entries[0]["target"] == f"session:{session.id}"

    async def test_raises_for_missing_session(self) -> None:
        service = _service()

        with pytest.raises(SessionNotFoundError):
            await service.revoke_session(uuid.uuid4(), uuid.uuid4())

    async def test_raises_for_foreign_session(self) -> None:
        session = _active_session(uuid.uuid4())
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())

        with pytest.raises(SessionNotFoundError):
            await service.revoke_session(uuid.uuid4(), session.id)

        assert repo.revoked == []

    async def test_revoking_a_terminated_session_raises_not_found(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        session.status = SessionStatus.REVOKED
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())

        with pytest.raises(SessionNotFoundError):
            await service.revoke_session(user_id, session.id)

        assert repo.revoked == []


class TestRevokeAllSessions:
    async def test_delegates_to_repo(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo, FakeAuditService())
        user_id = uuid.uuid4()

        await service.revoke_all_sessions(str(user_id))

        assert repo.revoked_for_users == [user_id]

    async def test_audits_revoked_all(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        repo = FakeSessionRepo([session])
        audit = FakeAuditService()
        service = SessionService(repo, audit)

        await service.revoke_all_sessions(user_id)

        assert audit.entries[0]["action"] == SESSION_REVOKED_ALL
        assert audit.entries[0]["target"] == f"user:{user_id}"
        assert audit.entries[0]["tenant_id"] == str(session.tenant_id)


class TestExpireSession:
    async def test_transitions_active_to_expired(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())

        result = await service.expire_session(session.id)

        assert result is not None
        assert result.status is SessionStatus.EXPIRED
        assert session.status is SessionStatus.EXPIRED
        assert repo.expired == [session.id]

    async def test_noop_when_session_missing(self) -> None:
        service = _service()

        assert await service.expire_session(uuid.uuid4()) is None

    async def test_does_not_rewrite_terminal_status(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        session.status = SessionStatus.REVOKED
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())

        result = await service.expire_session(session.id)

        assert result is not None
        assert result.status is SessionStatus.REVOKED
        assert repo.expired == []


class TestCommit:
    async def test_delegates_to_repo(self) -> None:
        repo = FakeSessionRepo()
        service = SessionService(repo, FakeAuditService())

        await service.commit()

        assert repo.committed is True


class TestRotateSession:
    async def test_rotates_hash_in_place_preserving_family(self) -> None:
        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        session = _active_session(user_id, family_id=family_id)
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())
        new_hash = "rotated-hash"

        rotated = await service.rotate_session(
            session.id, refresh_token_hash=new_hash, expires_at=datetime.now(UTC)
        )

        assert rotated is not None
        assert rotated.refresh_token_hash == new_hash
        assert rotated.token_family_id == family_id
        assert rotated.status is SessionStatus.ACTIVE

    async def test_noop_when_session_missing(self) -> None:
        service = _service()

        assert (
            await service.rotate_session(
                uuid.uuid4(), refresh_token_hash="h", expires_at=datetime.now(UTC)
            )
            is None
        )

    async def test_does_not_rotate_a_revoked_session(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        session.status = SessionStatus.REVOKED
        repo = FakeSessionRepo([session])
        service = SessionService(repo, FakeAuditService())

        result = await service.rotate_session(
            session.id, refresh_token_hash="new-hash", expires_at=datetime.now(UTC)
        )

        assert result is not None
        assert result.status is SessionStatus.REVOKED
        assert result.refresh_token_hash == "h"


class TestRevokeFamily:
    async def test_revokes_every_session_in_the_family(self) -> None:
        user_id = uuid.uuid4()
        family_id = uuid.uuid4()
        first = _active_session(user_id, family_id=family_id)
        second = _active_session(user_id, family_id=family_id)
        other = _active_session(user_id, family_id=uuid.uuid4())
        repo = FakeSessionRepo([first, second, other])
        service = SessionService(repo, FakeAuditService())

        await service.revoke_family(family_id)

        assert repo.revoked_families == [family_id]
        assert first.status is SessionStatus.REVOKED
        assert second.status is SessionStatus.REVOKED
        assert other.status is SessionStatus.ACTIVE


class TestMarkTrusted:
    async def test_marks_owned_active_session_trusted(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        repo = FakeSessionRepo([session])
        audit = FakeAuditService()
        service = SessionService(repo, audit)

        await service.mark_trusted(user_id, session.id, is_trusted=True)

        assert session.is_trusted is True
        assert audit.entries[0]["action"] == SESSION_TRUSTED
        assert audit.entries[0]["target"] == f"session:{session.id}"

    async def test_untrusting_does_not_audit(self) -> None:
        user_id = uuid.uuid4()
        session = _active_session(user_id)
        session.is_trusted = True
        repo = FakeSessionRepo([session])
        audit = FakeAuditService()
        service = SessionService(repo, audit)

        await service.mark_trusted(user_id, session.id, is_trusted=False)

        assert session.is_trusted is False
        assert audit.entries == []

    async def test_raises_for_foreign_or_terminated_session(self) -> None:
        user_id = uuid.uuid4()
        foreign = _active_session(uuid.uuid4())
        terminated = _active_session(user_id)
        terminated.status = SessionStatus.REVOKED
        repo = FakeSessionRepo([foreign, terminated])
        service = SessionService(repo, FakeAuditService())

        with pytest.raises(SessionNotFoundError):
            await service.mark_trusted(user_id, foreign.id, is_trusted=True)
        with pytest.raises(SessionNotFoundError):
            await service.mark_trusted(user_id, terminated.id, is_trusted=True)


class TestSessionCap:
    async def test_evicts_oldest_sessions_beyond_the_cap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "MAX_CONCURRENT_SESSIONS", 2)
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        repo = FakeSessionRepo()
        audit = FakeAuditService()
        service = SessionService(repo, audit)

        first = await service.create_session(
            user_id=user_id, tenant_id=tenant_id, refresh_token_hash="a"
        )
        second = await service.create_session(
            user_id=user_id, tenant_id=tenant_id, refresh_token_hash="b"
        )
        third = await service.create_session(
            user_id=user_id, tenant_id=tenant_id, refresh_token_hash="c"
        )

        assert first.status is SessionStatus.REVOKED
        assert second.status is SessionStatus.ACTIVE
        assert third.status is SessionStatus.ACTIVE
        evictions = [
            entry
            for entry in audit.entries
            if entry["action"] == SESSION_REVOKED
            and entry.get("details") == {"reason": "session_cap_evicted"}
        ]
        assert [entry["target"] for entry in evictions] == [f"session:{first.id}"]

    async def test_no_eviction_under_the_cap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "MAX_CONCURRENT_SESSIONS", 5)
        user_id, tenant_id = uuid.uuid4(), uuid.uuid4()
        repo = FakeSessionRepo()
        service = SessionService(repo, FakeAuditService())

        for i in range(3):
            await service.create_session(
                user_id=user_id, tenant_id=tenant_id, refresh_token_hash=f"h{i}"
            )

        sessions = await service.list_user_sessions(user_id)
        assert len(sessions) == 3
        assert all(s.status is SessionStatus.ACTIVE for s in sessions)
