"""User repository — DB operations for the users table.

All SQLAlchemy stays in this file. Repositories are the only layer allowed to
touch ORM models; service-facing methods accept and return domain entities
(``identity.domain.entities.User``). All queries are tenant-scoped: when no
tenant_id is passed the current request tenant is used (see TenantContext) and
RLS additionally enforces it.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from identity.core.tenant_context import TenantContext
from identity.db.repository import SqlRepository
from identity.domain.entities import User
from identity.models.user import UserModel
from skyrict_common.exceptions import UserNotFoundError


def _to_orm(user: User) -> UserModel:
    """Map a domain entity to a new ORM model (id is DB-generated unless set)."""
    model_kwargs: dict[str, Any] = {
        "tenant_id": user.tenant_id,
        "email": user.email,
        "password_hash": user.password_hash,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "mfa_enabled": user.mfa_enabled,
        "mfa_secret": user.mfa_secret,
        "mfa_backup_codes": user.mfa_backup_codes or None,
    }
    if user.id is not None:
        model_kwargs["id"] = user.id
    return UserModel(**model_kwargs)


def _from_orm(model: UserModel) -> User:
    """Map an ORM model to a domain entity."""
    return User(
        id=model.id,
        tenant_id=model.tenant_id,
        email=model.email,
        password_hash=model.password_hash,
        full_name=model.full_name,
        is_active=model.is_active,
        is_verified=model.is_verified,
        mfa_enabled=model.mfa_enabled,
        mfa_secret=model.mfa_secret,
        mfa_backup_codes=list(model.mfa_backup_codes) if model.mfa_backup_codes else [],
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class UserRepository(SqlRepository):
    """Repository for user persistence (implements ``UserRepositoryPort``)."""

    async def get_by_id(self, user_id: str | uuid.UUID) -> User | None:
        """Fetch a user by primary key, or None when absent."""
        model = await self.session.get(UserModel, user_id)
        return _from_orm(model) if model is not None else None

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> User | None:
        """Fetch a user by email within a tenant."""
        stmt = select(UserModel).where(
            UserModel.tenant_id == tenant_id,
            UserModel.email == email,
        )
        result = await self.session.execute(stmt)
        model = result.scalar_one_or_none()
        return _from_orm(model) if model is not None else None

    async def email_exists(self, tenant_id: str | uuid.UUID, email: str) -> bool:
        """Check if a user with this email already exists within a tenant."""
        user = await self.get_by_email(tenant_id, email)
        return user is not None

    async def create(self, user: User) -> User:
        """Persist a new user and return it with its DB-generated id."""
        model = _to_orm(user)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def update_profile(
        self,
        user_id: str | uuid.UUID,
        *,
        full_name: str | None = None,
        email: str | None = None,
    ) -> User:
        """Apply profile field updates and flush."""
        model = await self.session.get(UserModel, user_id)
        if model is None:
            raise UserNotFoundError("User not found")
        if full_name is not None:
            model.full_name = full_name
        if email is not None:
            model.email = email
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def update_password_hash(self, user_id: str | uuid.UUID, password_hash: str) -> User:
        """Store a new password hash and flush."""
        model = await self.session.get(UserModel, user_id)
        if model is None:
            raise UserNotFoundError("User not found")
        model.password_hash = password_hash
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def update_mfa(
        self,
        user_id: str | uuid.UUID,
        *,
        mfa_enabled: bool | None = None,
        mfa_secret: str | None = None,
        mfa_backup_codes: list[str | None] | None = None,
    ) -> User:
        """Apply the provided MFA field updates; ``None`` leaves a field unchanged."""
        model = await self.session.get(UserModel, user_id)
        if model is None:
            raise UserNotFoundError("User not found")
        if mfa_enabled is not None:
            model.mfa_enabled = mfa_enabled
        if mfa_secret is not None:
            model.mfa_secret = mfa_secret
        if mfa_backup_codes is not None:
            model.mfa_backup_codes = mfa_backup_codes
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def disable_mfa(self, user_id: str | uuid.UUID) -> User:
        """Clear every MFA field (secret, backup codes, enabled flag) and flush."""
        model = await self.session.get(UserModel, user_id)
        if model is None:
            raise UserNotFoundError("User not found")
        model.mfa_enabled = False
        model.mfa_secret = None
        model.mfa_backup_codes = None
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def mark_verified(self, user_id: str | uuid.UUID) -> User:
        """Mark the user's email as verified (idempotent) and flush."""
        model = await self.session.get(UserModel, user_id)
        if model is None:
            raise UserNotFoundError("User not found")
        model.is_verified = True
        await self.session.flush()
        await self.session.refresh(model)
        return _from_orm(model)

    async def list_active(
        self,
        *,
        tenant_id: str | uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[User]:
        """List all active users for a tenant."""
        tid: str | uuid.UUID = tenant_id or TenantContext.get()
        stmt = (
            select(UserModel)
            .where(
                UserModel.is_active == True,  # noqa: E712
                UserModel.tenant_id == tid,
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [_from_orm(model) for model in result.scalars().all()]
