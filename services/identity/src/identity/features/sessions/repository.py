"""Session repository — DB operations for the sessions table.

All SQLAlchemy stays in this file. Service-facing methods accept and return
domain entities (``identity.domain.entities.Session``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select, update

from identity.db.repository import SqlRepository
from identity.domain.entities import Session, SessionStatus
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
        "status": session.status.value,
        "token_family_id": session.token_family_id,
        "is_trusted": session.is_trusted,
        "expires_at": session.expires_at,
        "last_active_at": session.last_active_at,
        "revoked_at": session.revoked_at,
        "expired_at": session.expired_at,
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
        status=SessionStatus(model.status),
        token_family_id=model.token_family_id,
        is_trusted=model.is_trusted,
        created_at=model.created_at,
        expires_at=model.expires_at,
        last_active_at=model.last_active_at,
        revoked_at=model.revoked_at,
        expired_at=model.expired_at,
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

    async def get_active_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> list[Session]:
        """Get all active, unexpired sessions for a user, newest first.

        When ``tenant_id`` is given the query is scoped to that tenant so admin
        surfaces (member sessions) only see the workspace the admin is in.
        """
        now = datetime.now(UTC)
        conditions = [
            SessionModel.user_id == user_id,
            SessionModel.status == SessionStatus.ACTIVE.value,
            SessionModel.expires_at > now,
        ]
        if tenant_id is not None:
            conditions.append(SessionModel.tenant_id == tenant_id)
        stmt = (
            select(SessionModel)
            .where(and_(*conditions))
            .order_by(SessionModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]

    async def get_active_by_family(self, family_id: str | uuid.UUID) -> list[Session]:
        """Get all active sessions sharing a token family, newest first."""
        now = datetime.now(UTC)
        stmt = (
            select(SessionModel)
            .where(
                and_(
                    SessionModel.token_family_id == family_id,
                    SessionModel.status == SessionStatus.ACTIVE.value,
                    SessionModel.expires_at > now,
                )
            )
            .order_by(SessionModel.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]

    async def revoke_all_for_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID | None = None
    ) -> None:
        """Revoke all active sessions for a user (optionally within one tenant)."""
        now = datetime.now(UTC)
        conditions = [
            SessionModel.user_id == user_id,
            SessionModel.status == SessionStatus.ACTIVE.value,
        ]
        if tenant_id is not None:
            conditions.append(SessionModel.tenant_id == tenant_id)
        stmt = (
            update(SessionModel)
            .where(and_(*conditions))
            .values(status=SessionStatus.REVOKED.value, revoked_at=now)
        )
        await self.session.execute(stmt)

    async def revoke_family(self, family_id: str | uuid.UUID) -> None:
        """Revoke every active session in a token family (reuse chain-kill)."""
        now = datetime.now(UTC)
        stmt = (
            update(SessionModel)
            .where(
                and_(
                    SessionModel.token_family_id == family_id,
                    SessionModel.status == SessionStatus.ACTIVE.value,
                )
            )
            .values(status=SessionStatus.REVOKED.value, revoked_at=now)
        )
        await self.session.execute(stmt)

    async def revoke_session(self, session_id: str | uuid.UUID) -> None:
        """Revoke a specific session (no-op when it does not exist)."""
        model = await self.session.get(SessionModel, session_id)
        if model is None:
            return
        model.status = SessionStatus.REVOKED.value
        model.revoked_at = datetime.now(UTC)
        await self.session.flush()

    async def set_trusted(self, session_id: str | uuid.UUID, is_trusted: bool) -> None:
        """Mark a session trusted (or untrusted) on a recognized device."""
        model = await self.session.get(SessionModel, session_id)
        if model is None:
            return
        model.is_trusted = is_trusted
        await self.session.flush()

    async def mark_expired(self, session_id: str | uuid.UUID) -> None:
        """Materialize the ACTIVE -> EXPIRED transition on a past-expiry session."""
        model = await self.session.get(SessionModel, session_id)
        if model is None:
            return
        model.status = SessionStatus.EXPIRED.value
        model.expired_at = datetime.now(UTC)
        await self.session.flush()

    async def rotate(
        self,
        session_id: str | uuid.UUID,
        *,
        refresh_token_hash: str,
        expires_at: datetime,
    ) -> None:
        model = await self.session.get(SessionModel, session_id)
        if model is None:
            return
        model.refresh_token_hash = refresh_token_hash
        model.expires_at = expires_at
        model.last_active_at = datetime.now(UTC)
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()
