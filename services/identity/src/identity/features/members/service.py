"""Member service — list, re-role, and remove workspace members.

Composes the users, memberships, roles, sessions, and audit features. All
persistence happens through their repositories/services; nothing here touches
ORM models or the DI layer directly.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from identity.core.audit_events import MEMBER_REMOVED, MEMBER_ROLE_UPDATED
from identity.core.state_machine import InvalidTransitionError
from identity.domain.entities import MembershipStatus, User
from identity.features.members.schemas import MemberResponse
from skyrict_common.exceptions import UserNotFoundError, ValidationError

if TYPE_CHECKING:
    from identity.domain.entities import Session
    from identity.features.audit.service import AuditService
    from identity.features.memberships.service import MembershipService
    from identity.features.roles.repository import RoleRepository
    from identity.features.sessions.service import SessionService
    from identity.features.users.ports import UserRepositoryPort

TENANT_OWNER = "tenant_owner"


class MemberService:
    """Owns the business rules for the member-management surface."""

    def __init__(
        self,
        user_repo: UserRepositoryPort,
        membership_service: MembershipService,
        role_repo: RoleRepository,
        session_service: SessionService,
        audit_service: AuditService,
    ) -> None:
        self.user_repo = user_repo
        self.membership_service = membership_service
        self.role_repo = role_repo
        self.session_service = session_service
        self.audit_service = audit_service

    async def list_members(
        self, tenant_id: str | uuid.UUID, viewer_id: str | uuid.UUID
    ) -> list[MemberResponse]:
        """List every ACTIVE member with their role and joined date.

        The membership row is the canonical source: it carries ``user_id``,
        ``joined_at``, and the primary ``role_id``. User and role details are
        resolved per row; the membership's ``joined_at`` (falling back to the
        user's ``created_at``) is the joined date surfaced to the UI.
        """
        memberships = await self.membership_service.list_members(
            tenant_id, status=MembershipStatus.ACTIVE, offset=0, limit=1000
        )

        rows: list[MemberResponse] = []
        for membership in memberships:
            if membership.user_id is None:
                continue
            user = await self.user_repo.get_by_id(membership.user_id)
            if user is None or user.id is None:
                continue

            role_name = ""
            if membership.role_id is not None:
                role = await self.role_repo.get_by_id(membership.role_id)
                if role is not None:
                    role_name = role.name

            rows.append(
                MemberResponse(
                    id=user.id,
                    email=user.email,
                    full_name=user.full_name,
                    role_name=role_name,
                    joined_at=membership.joined_at or user.created_at,
                    avatar_url=user.avatar_url,
                    is_self=str(user.id) == str(viewer_id),
                )
            )

        rows.sort(key=lambda row: row.joined_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return rows

    async def change_role(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        role_name: str,
        actor_user_id: str | uuid.UUID,
    ) -> None:
        """Swap a member's role to ``role_name`` (single-role replace).

        Replaces the member's role grant and keeps ``memberships.role_id`` in
        sync. The last ``tenant_owner`` cannot be demoted — the organization
        always needs at least one owner.
        """
        user = await self._require_active_member(tenant_id, user_id)

        role = await self.role_repo.get_by_name(tenant_id, role_name)
        if role is None or role.id is None:
            raise ValidationError(f"Role '{role_name}' does not exist in this organization")

        current_roles = await self.role_repo.get_roles_for_user(user_id, tenant_id)
        if TENANT_OWNER in current_roles and await self._is_last_owner(tenant_id):
            raise ValidationError("The organization must keep at least one owner")

        await self.role_repo.revoke_all_for_user(user_id, tenant_id)
        await self.role_repo.grant_to_user(
            user_id=user_id,
            role_id=role.id,
            tenant_id=tenant_id,
            scope_id=uuid.UUID(str(tenant_id)),
        )

        membership = await self.membership_service.get_by_user(user_id, tenant_id)
        if membership is not None and membership.id is not None:
            await self.membership_service.update_role(membership_id=membership.id, role_id=role.id)

        if user.id is not None:
            await self.audit_service.log(
                action=MEMBER_ROLE_UPDATED,
                target=f"user:{user.id}",
                user_id=str(actor_user_id),
                tenant_id=str(tenant_id),
                details={"role": role_name},
            )

    async def remove_member(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        actor_user_id: str | uuid.UUID,
    ) -> None:
        """Remove a member (soft deactivate) and lock them out.

        Deactivates the account, revokes every active session (forcing logout
        everywhere), and suspends the membership. The last owner cannot be
        removed, and a member cannot remove themselves.
        """
        if str(user_id) == str(actor_user_id):
            raise ValidationError("You cannot remove your own account from the workspace")

        user = await self._require_active_member(tenant_id, user_id)

        current_roles = await self.role_repo.get_roles_for_user(user_id, tenant_id)
        if TENANT_OWNER in current_roles and await self._is_last_owner(tenant_id):
            raise ValidationError("The organization must keep at least one owner")

        await self.user_repo.set_active(user_id, is_active=False)
        await self.session_service.revoke_all_sessions(user_id)

        membership = await self.membership_service.get_by_user(user_id, tenant_id)
        if membership is not None and membership.id is not None:
            with contextlib.suppress(InvalidTransitionError):
                # Already suspended (e.g. a legacy row) — the removal stands.
                await self.membership_service.suspend(membership_id=membership.id)

        if user.id is not None:
            await self.audit_service.log(
                action=MEMBER_REMOVED,
                target=f"user:{user.id}",
                user_id=str(actor_user_id),
                tenant_id=str(tenant_id),
            )

    async def list_member_sessions(
        self, tenant_id: str | uuid.UUID, user_id: str | uuid.UUID
    ) -> list[Session]:
        """List a member's active sessions within the routed tenant.

        Used by admins to audit which devices a member is signed in on. The
        member must belong to the tenant (``_require_active_member``); sessions
        are scoped to ``tenant_id`` so members of other organizations' sessions
        never leak in.
        """
        await self._require_active_member(tenant_id, user_id)
        return await self.session_service.list_user_sessions(user_id, tenant_id)

    async def revoke_member_session(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        session_id: str | uuid.UUID,
        actor_user_id: str | uuid.UUID,
    ) -> None:
        """Revoke a single session of a member (e.g. a lost or wrong device).

        Missing, foreign, and already-terminated sessions surface as
        ``SessionNotFoundError`` (404).
        """
        await self._require_active_member(tenant_id, user_id)
        await self.session_service.revoke_session(user_id, session_id, tenant_id)

    async def revoke_all_member_sessions(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        actor_user_id: str | uuid.UUID,
    ) -> None:
        """Log a member out of every device in this workspace.

        The target must be an active member, and the actor cannot run this
        against their own account (use the self-service sessions endpoints
        instead).
        """
        if str(user_id) == str(actor_user_id):
            raise ValidationError(
                "You cannot log yourself out from member management — use your security settings instead"
            )
        await self._require_active_member(tenant_id, user_id)
        await self.session_service.revoke_all_sessions(user_id, tenant_id)

    async def _require_active_member(
        self, tenant_id: str | uuid.UUID, user_id: str | uuid.UUID
    ) -> User:
        """Fetch a user belonging to this tenant, or raise when absent."""
        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.tenant_id != uuid.UUID(str(tenant_id)):
            raise UserNotFoundError("Member not found")
        return user

    async def _is_last_owner(self, tenant_id: str | uuid.UUID) -> bool:
        return await self.role_repo.count_users_with_role(tenant_id, TENANT_OWNER) <= 1
