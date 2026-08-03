"""Session repository — DB operations for the sessions table."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from identity.db.repository import BaseRepository
from identity.models.session import SessionModel

if TYPE_CHECKING:
    import uuid


class SessionRepository(BaseRepository[SessionModel]):
    """Repository for session CRUD operations."""

    model = SessionModel

    async def get_active_by_user(self, user_id: uuid.UUID) -> list[SessionModel]:
        """Get all active sessions for a user."""
        stmt = (
            select(SessionModel)
            .where(SessionModel.user_id == user_id, SessionModel.is_active == True)  # noqa: E712
            .order_by(SessionModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all active sessions for a user."""
        stmt = (
            update(SessionModel)
            .where(SessionModel.user_id == user_id, SessionModel.is_active == True)  # noqa: E712
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)

    async def revoke_session(self, session_id: uuid.UUID) -> None:
        """Revoke a specific session."""
        session = await self.get_by_id(session_id)
        if session:
            session.is_active = False
            session.revoked_at = datetime.now(UTC)
            await self.session.flush()
