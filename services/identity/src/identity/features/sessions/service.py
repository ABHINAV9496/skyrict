"""Session service — track, list, revoke user sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from identity.core.config import settings
from identity.domain.entities import Session
from skyrict_common.exceptions import SessionNotFoundError

if TYPE_CHECKING:
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


class SessionService:
    """Manages user sessions — creation, listing, revocation."""

    def __init__(self, session_repo: SessionRepositoryPort) -> None:
        self.session_repo = session_repo

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
    ) -> Session:
        """Create a new session record."""
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
            is_active=True,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            last_active_at=now,
        )
        return await self.session_repo.create(session)

    async def list_user_sessions(self, user_id: str | uuid.UUID) -> list[Session]:
        """List all active sessions for a user."""
        return await self.session_repo.get_active_by_user(user_id)

    async def has_prior_device(
        self,
        user_id: str | uuid.UUID,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> bool:
        sessions = await self.session_repo.get_active_by_user(user_id)
        return any(_same_device(session, user_agent, ip_address) for session in sessions)

    async def revoke_session(self, user_id: str | uuid.UUID, session_id: str | uuid.UUID) -> None:
        """Revoke a specific session."""
        session = await self.session_repo.get_by_id(session_id)
        if not session or session.user_id != uuid.UUID(str(user_id)):
            raise SessionNotFoundError()
        await self.session_repo.revoke_session(session_id)

    async def revoke_all_sessions(self, user_id: str | uuid.UUID) -> None:
        """Revoke all sessions for a user (force logout everywhere)."""
        await self.session_repo.revoke_all_for_user(user_id)
