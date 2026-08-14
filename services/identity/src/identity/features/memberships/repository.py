"""Membership repository — DB operations for the memberships table."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from identity.db.repository import SqlRepository
from identity.domain.entities import Membership, MembershipStatus
from identity.models.membership import MembershipModel


def _to_orm(membership: Membership) -> MembershipModel:
    model_kwargs: dict[str, Any] = {
        "tenant_id": membership.tenant_id,
        "invited_email": membership.invited_email,
        "user_id": membership.user_id,
        "status": membership.status,
        "role_id": membership.role_id,
        "invited_by_user_id": membership.invited_by_user_id,
        "invited_at": membership.invited_at,
        "joined_at": membership.joined_at,
        "suspended_at": membership.suspended_at,
    }
    if membership.id is not None:
        model_kwargs["id"] = membership.id
    return MembershipModel(**model_kwargs)


def _from_orm(model: MembershipModel) -> Membership:
    return Membership(
        id=model.id,
        tenant_id=model.tenant_id,
        invited_email=model.invited_email,
        user_id=model.user_id,
        status=model.status,
        role_id=model.role_id,
        invited_by_user_id=model.invited_by_user_id,
        invited_at=model.invited_at,
        joined_at=model.joined_at,
        suspended_at=model.suspended_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class MembershipRepository(SqlRepository):
    async def create(self, membership: Membership) -> Membership:
        model = _to_orm(membership)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def get_by_id(self, membership_id: str | uuid.UUID) -> Membership | None:
        model = await self.session.get(MembershipModel, membership_id)
        return _from_orm(model) if model is not None else None

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> Membership | None:
        stmt = select(MembershipModel).where(
            MembershipModel.tenant_id == tenant_id,
            MembershipModel.invited_email.ilike(email),
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def get_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> Membership | None:
        stmt = select(MembershipModel).where(
            MembershipModel.user_id == user_id,
            MembershipModel.tenant_id == tenant_id,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def list_by_tenant(
        self,
        tenant_id: str | uuid.UUID,
        *,
        status: MembershipStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Membership]:
        stmt = select(MembershipModel).where(MembershipModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(MembershipModel.status == status)
        stmt = stmt.order_by(MembershipModel.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]

    async def update_status(
        self,
        membership_id: str | uuid.UUID,
        *,
        status: MembershipStatus,
        suspended_at: datetime | None = None,
    ) -> Membership:
        model = await self.session.get(MembershipModel, membership_id)
        if model is None:
            from skyrict_common.exceptions import NotFoundError

            raise NotFoundError("Membership not found")
        model.status = status
        model.suspended_at = suspended_at
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def set_user(
        self,
        membership_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        *,
        joined_at: datetime,
    ) -> Membership:
        model = await self.session.get(MembershipModel, membership_id)
        if model is None:
            from skyrict_common.exceptions import NotFoundError

            raise NotFoundError("Membership not found")
        model.user_id = uuid.UUID(str(user_id))
        model.joined_at = joined_at
        model.status = MembershipStatus.ACTIVE
        model.suspended_at = None
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def update_role(
        self,
        membership_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
    ) -> Membership:
        """Swap a membership's primary role (kept in sync with the grant)."""
        model = await self.session.get(MembershipModel, membership_id)
        if model is None:
            from skyrict_common.exceptions import NotFoundError

            raise NotFoundError("Membership not found")
        model.role_id = uuid.UUID(str(role_id))
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)
