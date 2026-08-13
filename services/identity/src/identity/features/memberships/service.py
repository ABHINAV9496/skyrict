"""Membership service — lifecycle operations driven by the state machine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from identity.core.audit_events import (
    MEMBERSHIP_ACTIVATED,
    MEMBERSHIP_REINSTATED,
    MEMBERSHIP_SUSPENDED,
)
from identity.core.state_machine import StateMachine
from identity.domain.entities import Membership, MembershipStatus
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from identity.features.audit.service import AuditService
    from identity.features.memberships.ports import MembershipRepositoryPort

# invited -> active -> (suspended <-> active)
MEMBERSHIP_TRANSITIONS: dict[str, frozenset[str]] = {
    MembershipStatus.INVITED.value: frozenset({MembershipStatus.ACTIVE.value}),
    MembershipStatus.ACTIVE.value: frozenset({MembershipStatus.SUSPENDED.value}),
    MembershipStatus.SUSPENDED.value: frozenset({MembershipStatus.ACTIVE.value}),
}

membership_state_machine = StateMachine(MEMBERSHIP_TRANSITIONS, entity="membership")


class MembershipService:
    def __init__(
        self, membership_repo: MembershipRepositoryPort, audit_service: AuditService
    ) -> None:
        self.membership_repo = membership_repo
        self.audit_service = audit_service

    async def create_invited(
        self,
        *,
        tenant_id: str | uuid.UUID,
        email: str,
        role_id: str | uuid.UUID,
        invited_by_user_id: str | uuid.UUID,
    ) -> Membership:
        """Create an INVITED membership, reserving the email in the tenant."""
        tenant_id_uuid = uuid.UUID(str(tenant_id))
        normalized_email = email.strip().lower()

        existing = await self.membership_repo.get_by_email(tenant_id_uuid, normalized_email)
        if existing is not None:
            raise ValidationError("This email is already a member or invited in this organization")

        return await self.membership_repo.create(
            Membership(
                tenant_id=tenant_id_uuid,
                invited_email=normalized_email,
                status=MembershipStatus.INVITED,
                role_id=uuid.UUID(str(role_id)),
                invited_by_user_id=uuid.UUID(str(invited_by_user_id)),
                invited_at=datetime.now(UTC),
            )
        )

    async def create_active(
        self,
        *,
        tenant_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        role_id: str | uuid.UUID | None = None,
        invited_email: str | None = None,
    ) -> Membership:
        """Create an ACTIVE membership for a real user.

        Used by registration (tenant owner) and by the legacy accept path
        (invitations that predate migration 0009 have no linked membership).
        """
        tenant_id_uuid = uuid.UUID(str(tenant_id))
        user_id_uuid = uuid.UUID(str(user_id))
        existing = await self.membership_repo.get_by_user(user_id_uuid, tenant_id_uuid)
        if existing is not None:
            raise ValidationError("User is already a member of this organization")

        created = await self.membership_repo.create(
            Membership(
                tenant_id=tenant_id_uuid,
                user_id=user_id_uuid,
                invited_email=invited_email.strip().lower() if invited_email else None,
                status=MembershipStatus.ACTIVE,
                role_id=uuid.UUID(str(role_id)) if role_id is not None else None,
                joined_at=datetime.now(UTC),
            )
        )
        await self._audit_membership(MEMBERSHIP_ACTIVATED, created, user_id=user_id_uuid)
        return created

    async def activate(
        self,
        *,
        membership_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
    ) -> Membership:
        """Flip an INVITED membership to ACTIVE once the user materializes."""
        membership = await self._get(membership_id)
        membership_state_machine.transition(membership.status.value, MembershipStatus.ACTIVE.value)
        activated = await self.membership_repo.set_user(
            membership_id, user_id, joined_at=datetime.now(UTC)
        )
        await self._audit_membership(MEMBERSHIP_ACTIVATED, activated, user_id=user_id)
        return activated

    async def suspend(self, *, membership_id: str | uuid.UUID) -> Membership:
        """Suspend an ACTIVE membership."""
        membership = await self._get(membership_id)
        membership_state_machine.transition(
            membership.status.value, MembershipStatus.SUSPENDED.value
        )
        suspended = await self.membership_repo.update_status(
            membership_id,
            status=MembershipStatus.SUSPENDED,
            suspended_at=datetime.now(UTC),
        )
        await self._audit_membership(MEMBERSHIP_SUSPENDED, suspended)
        return suspended

    async def reinstate(self, *, membership_id: str | uuid.UUID) -> Membership:
        """Reactivate a SUSPENDED membership."""
        membership = await self._get(membership_id)
        membership_state_machine.transition(membership.status.value, MembershipStatus.ACTIVE.value)
        reinstated = await self.membership_repo.update_status(
            membership_id,
            status=MembershipStatus.ACTIVE,
            suspended_at=None,
        )
        await self._audit_membership(MEMBERSHIP_REINSTATED, reinstated)
        return reinstated

    async def get_by_id(self, membership_id: str | uuid.UUID) -> Membership:
        return await self._get(membership_id)

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> Membership | None:
        return await self.membership_repo.get_by_email(tenant_id, email)

    async def get_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> Membership | None:
        return await self.membership_repo.get_by_user(user_id, tenant_id)

    async def update_role(
        self,
        *,
        membership_id: str | uuid.UUID,
        role_id: str | uuid.UUID,
    ) -> Membership:
        """Swap the membership's primary role (kept in sync with the grant)."""
        return await self.membership_repo.update_role(membership_id, role_id)

    async def list_members(
        self,
        tenant_id: str | uuid.UUID,
        *,
        status: MembershipStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Membership]:
        return await self.membership_repo.list_by_tenant(
            tenant_id, status=status, offset=offset, limit=limit
        )

    async def _get(self, membership_id: str | uuid.UUID) -> Membership:
        membership = await self.membership_repo.get_by_id(membership_id)
        if membership is None:
            raise NotFoundError("Membership not found")
        return membership

    async def _audit_membership(
        self,
        action: str,
        membership: Membership,
        *,
        user_id: str | uuid.UUID | None = None,
    ) -> None:
        await self.audit_service.log(
            action=action,
            target=f"membership:{membership.id}",
            user_id=str(user_id) if user_id is not None else None,
            tenant_id=str(membership.tenant_id),
        )
