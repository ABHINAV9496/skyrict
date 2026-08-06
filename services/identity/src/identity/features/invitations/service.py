"""Invitation service — create, accept, and expire invite tokens."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from identity.core.config import settings
from identity.core.constants import INVITATION_TOKEN_EXPIRE_DAYS
from identity.core.email import EmailService
from identity.core.security import hash_invitation_token, hash_password, validate_password_policy
from identity.domain.entities import Invitation, User
from identity.features.invitations.ports import InvitationRepositoryPort
from skyrict_common.exceptions import (
    InvitationAlreadyUsedError,
    InvitationEmailMismatchError,
    InvitationExpiredError,
    InvitationNotFoundError,
    NotFoundError,
    UserAlreadyExistsError,
    ValidationError,
)

if TYPE_CHECKING:
    from identity.features.memberships.service import MembershipService
    from identity.features.roles.ports import RoleRepositoryPort
    from identity.features.users.ports import UserRepositoryPort


class InvitationService:
    def __init__(
        self,
        invitation_repo: InvitationRepositoryPort,
        user_repo: UserRepositoryPort,
        role_repo: RoleRepositoryPort,
        email_service: EmailService,
        membership_service: MembershipService,
    ) -> None:
        self.invitation_repo = invitation_repo
        self.user_repo = user_repo
        self.role_repo = role_repo
        self.email_service = email_service
        self.membership_service = membership_service

    async def create_invitation(
        self,
        *,
        tenant_id: str | uuid.UUID,
        email: str,
        role_name: str,
        created_by_user_id: str | uuid.UUID,
        inviter_name: str = "",
        organization_name: str = "",
    ) -> tuple[Invitation, str]:

        role = await self.role_repo.get_by_name(tenant_id, role_name)
        if role is None or role.id is None:
            raise ValidationError(f"Role '{role_name}' does not exist in this organization")

        existing_user = await self.user_repo.get_by_email(tenant_id, email)
        if existing_user is not None:
            raise ValidationError("A user with this email already exists in this organization")

        # The INVITED membership reserves the email within the tenant; it is
        # the canonical pending relationship (no placeholder user).
        membership = await self.membership_service.create_invited(
            tenant_id=tenant_id,
            email=email,
            role_id=role.id,
            invited_by_user_id=created_by_user_id,
        )

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(days=INVITATION_TOKEN_EXPIRE_DAYS)

        invitation = await self.invitation_repo.create(
            Invitation(
                tenant_id=uuid.UUID(str(tenant_id)),
                email=email,
                token_hash=hash_invitation_token(token),
                role_name=role_name,
                created_by_user_id=uuid.UUID(str(created_by_user_id)),
                expires_at=expires_at,
                membership_id=membership.id,
            )
        )

        await self.email_service.send_invitation(
            to=email,
            inviter_name=inviter_name,
            organization_name=organization_name,
            token=token,
            base_url=settings.EMAIL_VERIFICATION_BASE_URL or None,
        )

        return invitation, token

    async def accept_invitation(
        self,
        *,
        token: str,
        email: str,
        password: str,
        full_name: str,
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

        validate_password_policy(password)

        tenant_id = invitation.tenant_id

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

        assert invitation.id is not None
        assert user.id is not None

        role = await self.role_repo.get_by_name(tenant_id, invitation.role_name)
        if role is None or role.id is None:
            raise ValidationError(
                f"Role '{invitation.role_name}' no longer exists in this organization"
            )
        await self.role_repo.grant_to_user(
            user_id=user.id,
            role_id=role.id,
            tenant_id=tenant_id,
            scope_id=uuid.UUID(str(tenant_id)),
        )

        if invitation.membership_id is not None:
            await self.membership_service.activate(
                membership_id=invitation.membership_id, user_id=user.id
            )
        else:
            # Legacy invitation (pre-0009): no linked membership exists, so
            # materialize an ACTIVE membership for the new user.
            await self.membership_service.create_active(
                tenant_id=tenant_id,
                user_id=user.id,
                role_id=role.id,
                invited_email=email,
            )

        await self.invitation_repo.mark_used(invitation.id, user.id)

        return user

    async def expire_invitation(
        self, invitation_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> None:
        try:
            await self.invitation_repo.mark_used(invitation_id, None)
        except NotFoundError as exc:
            raise InvitationNotFoundError("Invitation not found") from exc
