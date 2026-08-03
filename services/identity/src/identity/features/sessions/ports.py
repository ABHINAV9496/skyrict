"""Session repository port — the persistence contract the sessions service depends on.

Ports abstract persistence only (never business rules). Methods accept and
return domain entities; SQLAlchemy lives in the concrete implementation
``identity.features.sessions.repository``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from identity.domain.entities import Session

if TYPE_CHECKING:
    import uuid


class SessionRepositoryPort(Protocol):
    """Persistence operations for user sessions."""

    async def get_by_id(self, session_id: str | uuid.UUID) -> Session | None: ...

    async def create(self, session: Session) -> Session: ...

    async def get_active_by_user(self, user_id: str | uuid.UUID) -> list[Session]: ...

    async def revoke_session(self, session_id: str | uuid.UUID) -> None: ...

    async def revoke_all_for_user(self, user_id: str | uuid.UUID) -> None: ...
