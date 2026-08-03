"""Session repository — DB operations for the sessions table.

All SQLAlchemy stays in this file. Service-facing methods accept and return
domain entities (``identity.domain.entities.Session``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from identity.db.repository import SqlRepository
from identity.domain.entities import Session
from identity.models.session import SessionModel


def _to_orm(session: Session) -> SessionModel:
    """Map a domain entity to a new ORM model (id is DB-generated unless set)."""
    model_kwargs: dict[str, Any] = {
        "user_id": session.user_id,
        "tenant_id": session.tenant_id,
        "refresh_token_hash": session.refresh_token_hash,
        "device_info": session.device_info,
        "ip_address": session.ip_address,
        "user_agent": session.user_agent,
        "location": session.location,
        "is_active": session.is_active,
        "expires_at": session.expires_at,
        "last_active_at": session.last_active_at,
        "revoked_at": session.revoked_at,
    }
    if session.id is not None:
        model_kwargs["id"] = session.id
    return SessionModel(**model_kwargs)


def _from_orm(model: SessionModel) -> Session:
    """Map an ORM model to a domain entity."""
    return Session(
        id=model.id,
        user_id=model.user_id,
        tenant_id=model.tenant_id,
        refresh_token_hash=model.refresh_token_hash,
        device_info=model.device_info,
        ip_address=model.ip_address,
        user_agent=model.user_agent,
        location=model.location,
        is_active=model.is_active,
        created_at=model.created_at,
        expires_at=model.expires_at,
        last_active_at=model.last_active_at,
        revoked_at=model.revoked_at,
    )


class SessionRepository(SqlRepository):
    """Repository for session persistence (implements ``SessionRepositoryPort``)."""

    async def get_by_id(self, session_id: str | uuid.UUID) -> Session | None:
        """Fetch a session by primary key, or None when absent."""
        model = await self.session.get(SessionModel, session_id)
        return _from_orm(model) if model is not None else None

    async def create(self, session: Session) -> Session:
        """Persist a new session and return it with its DB-generated id."""
        model = _to_orm(session)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def get_active_by_user(self, user_id: str | uuid.UUID) -> list[Session]:
        """Get all active sessions for a user, newest first."""
        stmt = (
            select(SessionModel)
            .where(SessionModel.user_id == user_id, SessionModel.is_active == True)  # noqa: E712
            .order_by(SessionModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]

    async def revoke_all_for_user(self, user_id: str | uuid.UUID) -> None:
        """Revoke all active sessions for a user."""
        stmt = (
            update(SessionModel)
            .where(SessionModel.user_id == user_id, SessionModel.is_active == True)  # noqa: E712
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )
        await self.session.execute(stmt)

    async def revoke_session(self, session_id: str | uuid.UUID) -> None:
        """Revoke a specific session (no-op when it does not exist)."""
        model = await self.session.get(SessionModel, session_id)
        if model is None:
            return
        model.is_active = False
        model.revoked_at = datetime.now(UTC)
        await self.session.flush()
