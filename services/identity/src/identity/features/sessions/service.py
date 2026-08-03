"""Session service — track, list, revoke user sessions.

Owns the business rules (session TTL policy, not-found handling). All
persistence goes through the ``SessionRepositoryPort``; no ORM models or
sessions are touched here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from identity.domain.entities import Session
from skyrict_common.exceptions import SessionNotFoundError

if TYPE_CHECKING:
    import uuid

    from identity.features.sessions.ports import SessionRepositoryPort


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
    ) -> Session:
        """Create a new session record."""
        now = datetime.now(UTC)
        session = Session(
            user_id=user_id,
            tenant_id=tenant_id,
            refresh_token_hash=refresh_token_hash,
            user_agent=user_agent,
            ip_address=ip_address,
            device_info=device_info,
            location=location,
            is_active=True,
            expires_at=now + timedelta(days=7),
            last_active_at=now,
        )
        return await self.session_repo.create(session)

    async def list_user_sessions(self, user_id: str | uuid.UUID) -> list[Session]:
        """List all active sessions for a user."""
        return await self.session_repo.get_active_by_user(user_id)

    async def revoke_session(self, session_id: str | uuid.UUID) -> None:
        """Revoke a specific session."""
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise SessionNotFoundError()
        await self.session_repo.revoke_session(session_id)

    async def revoke_all_sessions(self, user_id: str | uuid.UUID) -> None:
        """Revoke all sessions for a user (force logout everywhere)."""
        await self.session_repo.revoke_all_for_user(user_id)
