"""Invitation service — create, accept, and expire invite tokens."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from identity.core.config import settings
from identity.core.constants import DEFAULT_INVITE_ROLE, INVITATION_TOKEN_EXPIRE_DAYS
from identity.core.email import EmailService
from identity.core.security import hash_password
from identity.domain.entities import Invitation, User
from identity.features.invitations.ports import InvitationRepositoryPort
from skyrict_common.exceptions import (
    InvitationAlreadyUsedError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    NotFoundError,
    UserAlreadyExistsError,
)

if TYPE_CHECKING:
    from identity.features.roles.ports import RoleRepositoryPort
    from identity.features.users.ports import UserRepositoryPort


class InvitationService:
    def __init__(
        self,
        invitation_repo: InvitationRepositoryPort,
        user_repo: UserRepositoryPort,
        role_repo: RoleRepositoryPort,
        email_service: EmailService,
    ) -> None:
        self.invitation_repo = invitation_repo
        self.user_repo = user_repo
        self.role_repo = role_repo
        self.email_service = email_service

    async def create_invitation(
        self,
        *,
        tenant_id: str | uuid.UUID,
        email: str,
        role_name: str,
        created_by_user_id: str | uuid.UUID,
        inviter_name: str = "",
        organization_name: str = "",
    ) -> Invitation:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(days=INVITATION_TOKEN_EXPIRE_DAYS)

        invitation = await self.invitation_repo.create(
            Invitation(
                tenant_id=uuid.UUID(str(tenant_id)),
                email=email,
                token=token,
                created_by_user_id=uuid.UUID(str(created_by_user_id)),
                expires_at=expires_at,
            )
        )

        await self.email_service.send_invitation(
            to=email,
            inviter_name=inviter_name,
            organization_name=organization_name,
            token=token,
            base_url=settings.EMAIL_VERIFICATION_BASE_URL or None,
        )

        return invitation

    async def accept_invitation(
        self,
        *,
        token: str,
        email: str,
        password: str,
        full_name: str,
        tenant_id: str | uuid.UUID,
    ) -> User:
        invitation = await self.invitation_repo.get_by_token(token)
        if invitation is None:
            raise InvitationNotFoundError("Invalid invitation token")

        if invitation.expires_at < datetime.now(UTC):
            raise InvitationExpiredError("Invitation has expired")

        if invitation.used_at is not None:
            raise InvitationAlreadyUsedError("Invitation has already been used")

        if invitation.email.lower() != email.lower():
            raise InvitationEmailMismatchError("Email does not match the invitation")

        existing = await self.user_repo.get_by_email(tenant_id, email)
        if existing is not None:
            raise UserAlreadyExistsError(
                "A user with this email already exists in this organization"
            )

        user = await self.user_repo.create(
            User(
                tenant_id=uuid.UUID(str(tenant_id)),
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                is_active=True,
                is_verified=True,
            )
        )

        assert user.id is not None

        role = await self.role_repo.get_by_name(tenant_id, DEFAULT_INVITE_ROLE)
        if role is not None and role.id is not None:
            await self.role_repo.grant_to_user(
                user_id=user.id,
                role_id=role.id,
                tenant_id=tenant_id,
                scope_id=uuid.UUID(str(tenant_id)),
            )

        assert invitation.id is not None
        assert user.id is not None

        await self.invitation_repo.mark_used(invitation.id, user.id)

        return user

    async def expire_invitation(
        self, invitation_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> None:
        try:
            await self.invitation_repo.mark_used(invitation_id, invitation_id)
        except NotFoundError as exc:
            raise InvitationNotFoundError("Invitation not found") from exc
