"""Handoff repository — DB operations for the handoff_tokens table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from identity.db.repository import SqlRepository
from identity.domain.entities import Handoff
from identity.models.handoff import HandoffModel


def _to_orm(handoff: Handoff) -> HandoffModel:
    model_kwargs: dict[str, Any] = {
        "purpose": handoff.purpose,
        "token_hash": handoff.token_hash,
        "payload": handoff.payload,
        "expires_at": handoff.expires_at,
    }
    if handoff.tenant_id is not None:
        model_kwargs["tenant_id"] = handoff.tenant_id
    if handoff.created_by_user_id is not None:
        model_kwargs["created_by_user_id"] = handoff.created_by_user_id
    if handoff.id is not None:
        model_kwargs["id"] = handoff.id
    if handoff.consumed_at is not None:
        model_kwargs["consumed_at"] = handoff.consumed_at
    return HandoffModel(**model_kwargs)


def _from_orm(model: HandoffModel) -> Handoff:
    return Handoff(
        id=model.id,
        purpose=model.purpose,
        token_hash=model.token_hash,
        payload=model.payload,
        tenant_id=model.tenant_id,
        created_by_user_id=model.created_by_user_id,
        expires_at=model.expires_at,
        consumed_at=model.consumed_at,
        created_at=model.created_at,
    )


class HandoffRepository(SqlRepository):
    async def create(self, handoff: Handoff) -> Handoff:
        model = _to_orm(handoff)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def get_by_hash(self, token_hash: str) -> Handoff | None:
        stmt = select(HandoffModel).where(HandoffModel.token_hash == token_hash)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def mark_consumed(self, handoff_id: str | uuid.UUID) -> Handoff | None:
        model = await self.session.get(HandoffModel, handoff_id)
        if model is None:
            return None
        model.consumed_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)
