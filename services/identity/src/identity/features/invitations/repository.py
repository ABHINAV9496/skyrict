"""Invitation repository — DB operations for the invitations table."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from identity.db.repository import SqlRepository
from identity.domain.entities import Invitation
from identity.models.invitation import InvitationModel


def _to_orm(invitation: Invitation) -> InvitationModel:
    model_kwargs: dict[str, Any] = {
        "tenant_id": invitation.tenant_id,
        "email": invitation.email,
        "token": invitation.token,
        "created_by_user_id": invitation.created_by_user_id,
        "expires_at": invitation.expires_at,
    }
    if invitation.id is not None:
        model_kwargs["id"] = invitation.id
    if invitation.used_at is not None:
        model_kwargs["used_at"] = invitation.used_at
    if invitation.used_by_user_id is not None:
        model_kwargs["used_by_user_id"] = invitation.used_by_user_id
    return InvitationModel(**model_kwargs)


def _from_orm(model: InvitationModel) -> Invitation:
    return Invitation(
        id=model.id,
        tenant_id=model.tenant_id,
        email=model.email,
        token=model.token,
        created_by_user_id=model.created_by_user_id,
        expires_at=model.expires_at,
        used_at=model.used_at,
        used_by_user_id=model.used_by_user_id,
        created_at=model.created_at,
    )


class InvitationRepository(SqlRepository):
    async def create(self, invitation: Invitation) -> Invitation:
        model = _to_orm(invitation)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def get_by_token(self, token: str) -> Invitation | None:
        stmt = select(InvitationModel).where(InvitationModel.token == token)
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def mark_used(
        self, invitation_id: str | uuid.UUID, user_id: str | uuid.UUID
    ) -> Invitation:
        model = await self.session.get(InvitationModel, invitation_id)
        if model is None:
            from skyrict_common.exceptions import NotFoundError

            raise NotFoundError("Invitation not found")
        model.used_at = datetime.now(UTC)
        model.used_by_user_id = uuid.UUID(str(user_id))
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def list_by_tenant(
        self, tenant_id: str | uuid.UUID, *, offset: int = 0, limit: int = 20
    ) -> list[Invitation]:
        stmt = (
            select(InvitationModel)
            .where(InvitationModel.tenant_id == tenant_id)
            .order_by(InvitationModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]
