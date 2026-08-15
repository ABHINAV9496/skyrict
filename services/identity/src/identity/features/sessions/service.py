"""Session service — track, list, revoke, expire user sessions.

Owns the session lifecycle. Every status mutation passes through the
``SESSION_STATE_MACHINE`` so invalid hops fail fast. All persistence goes
through the ``SessionRepositoryPort``; audit entries are produced for every
security-relevant transition.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from identity.core.audit_events import (
    SESSION_CREATED,
    SESSION_REVOKED,
    SESSION_REVOKED_ALL,
    SESSION_TRUSTED,
)
from identity.core.config import settings
from identity.core.state_machine import StateMachine
from identity.domain.entities import Session, SessionStatus
from skyrict_common.exceptions import SessionNotFoundError

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService
    from identity.features.sessions.ports import SessionRepositoryPort


def _normalize_user_agent(user_agent: str | None) -> str:
    return " ".join((user_agent or "").lower().split())


def _ip_prefix(ip_address: str | None) -> str:
    if not ip_address:
        return ""
    return ".".join(ip_address.split(".")[:3])


def _same_device(session: Session, user_agent: str | None, ip_address: str | None) -> bool:
    return _normalize_user_agent(session.user_agent) == _normalize_user_agent(
        user_agent
    ) and _ip_prefix(session.ip_address) == _ip_prefix(ip_address)


# Session lifecycle: active is the only live state; revocation and expiry are
# terminal. There is no path back into active.
SESSION_STATE_MACHINE = StateMachine(
    {
        SessionStatus.ACTIVE.value: (
            SessionStatus.REVOKED.value,
            SessionStatus.EXPIRED.value,
        ),
    },
    entity="session",
)


class SessionService:
    """Manages user sessions — creation, listing, revocation, expiry."""

    def __init__(self, session_repo: SessionRepositoryPort, audit_service: AuditService) -> None:
        self.session_repo = session_repo
        self.audit_service = audit_service

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID,
        refresh_token_hash: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
        device_info: dict[str, Any] | None = None,
        location: str | None = None,
        session_id: uuid.UUID | None = None,
        token_family_id: uuid.UUID | None = None,
    ) -> Session:
        """Create a new active session record in its own token family."""
        now = datetime.now(UTC)
        session = Session(
            id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent,
            ip_address=ip_address,
            device_info=device_info,
            location=location,
            status=SessionStatus.ACTIVE,
            token_family_id=token_family_id or uuid.uuid4(),
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            last_active_at=now,
        )
        created = await self.session_repo.create(session)
        await self.audit_service.log(
            action=SESSION_CREATED,
            target=f"session:{created.id}",
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._enforce_session_cap(user_id, tenant_id)
        return created

    async def _enforce_session_cap(self, user_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Evict the oldest sessions once the per-user active-session cap is exceeded."""
        cap = settings.MAX_CONCURRENT_SESSIONS
        if cap <= 0:
            return
        active = await self.session_repo.get_active_by_user(user_id)
        for stale in active[cap:]:
            assert stale.id is not None
            await self.session_repo.revoke_session(stale.id)
            await self.audit_service.log(
                action=SESSION_REVOKED,
                target=f"session:{stale.id}",
                user_id=str(user_id),
                tenant_id=str(tenant_id),
                details={"reason": "session_cap_evicted"},
            )

    async def list_user_sessions(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> list[Session]:
        """List all active, unexpired sessions for a user.

        When ``tenant_id`` is given only sessions in that tenant are returned
        (used by the member-management surface).
        """
        return await self.session_repo.get_active_by_user(user_id, tenant_id)

    async def get_session(self, session_id: str | uuid.UUID) -> Session | None:
        """Fetch a session by id (any status), or None when absent."""
        return await self.session_repo.get_by_id(session_id)

    async def has_prior_device(
        self,
        user_id: str | uuid.UUID,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> bool:
        sessions = await self.session_repo.get_active_by_user(user_id)
        return any(_same_device(session, user_agent, ip_address) for session in sessions)

    async def revoke_session(
        self,
        user_id: str | uuid.UUID,
        session_id: str | uuid.UUID,
        tenant_id: str | uuid.UUID | None = None,
    ) -> None:
        """Revoke a specific session (active -> revoked).

        Missing, foreign, and already-terminated sessions all surface as
        ``SessionNotFoundError`` (404) so double-revoke stays idempotent. When
        ``tenant_id`` is given, a session outside that tenant is treated as
        foreign as well.
        """
        session = await self.session_repo.get_by_id(session_id)
        if (
            not session
            or session.user_id != uuid.UUID(str(user_id))
            or (tenant_id is not None and session.tenant_id != uuid.UUID(str(tenant_id)))
            or session.status is not SessionStatus.ACTIVE
        ):
            raise SessionNotFoundError()
        SESSION_STATE_MACHINE.transition(session.status.value, SessionStatus.REVOKED.value)
        await self.session_repo.revoke_session(session_id)
        await self.audit_service.log(
            action=SESSION_REVOKED,
            target=f"session:{session_id}",
            user_id=str(user_id),
            tenant_id=str(session.tenant_id),
        )

    async def rotate_session(
        self,
        session_id: str | uuid.UUID,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> Session | None:
        """Rotate a session's refresh hash in place, preserving its token family."""
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            return None
        if session.status is SessionStatus.ACTIVE:
            await self.session_repo.rotate(
                session_id,
                refresh_token_hash=refresh_token_hash,
                expires_at=expires_at,
            )
            return await self.session_repo.get_by_id(session_id)
        return session

    async def revoke_family(self, family_id: str | uuid.UUID) -> None:
        """Revoke every active session sharing a token family (reuse chain-kill)."""
        await self.session_repo.revoke_family(family_id)

    async def mark_trusted(
        self,
        user_id: str | uuid.UUID,
        session_id: str | uuid.UUID,
        *,
        is_trusted: bool,
    ) -> None:
        """Mark a session as a recognized (trusted) device.

        Missing, foreign, and already-terminated sessions surface as
        ``SessionNotFoundError`` (404), mirroring revocation semantics.
        """
        session = await self.session_repo.get_by_id(session_id)
        if (
            not session
            or session.user_id != uuid.UUID(str(user_id))
            or session.status is not SessionStatus.ACTIVE
        ):
            raise SessionNotFoundError()
        await self.session_repo.set_trusted(session_id, is_trusted)
        if is_trusted:
            await self.audit_service.log(
                action=SESSION_TRUSTED,
                target=f"session:{session_id}",
                user_id=str(user_id),
                tenant_id=str(session.tenant_id),
            )

    async def revoke_all_sessions(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> None:
        """Revoke all sessions for a user (force logout everywhere).

        When ``tenant_id`` is given only that tenant's sessions are revoked —
        used to log a member out of the current workspace without touching
        their sessions in other organizations.
        """
        active = await self.session_repo.get_active_by_user(user_id, tenant_id)
        await self.session_repo.revoke_all_for_user(user_id, tenant_id)
        if active:
            await self.audit_service.log(
                action=SESSION_REVOKED_ALL,
                target=f"user:{user_id}",
                user_id=str(user_id),
                tenant_id=str(active[0].tenant_id),
            )

    async def expire_session(self, session_id: str | uuid.UUID) -> Session | None:
        """Materialize the active -> expired transition for a past-expiry session."""
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            return None
        if session.status is SessionStatus.ACTIVE:
            SESSION_STATE_MACHINE.transition(session.status.value, SessionStatus.EXPIRED.value)
            await self.session_repo.mark_expired(session_id)
            return await self.session_repo.get_by_id(session_id)
        return session

    async def commit(self) -> None:
        await self.session_repo.commit()
