"""Unit tests for the membership feature MembershipService (fake port)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from identity.core.state_machine import InvalidTransitionError
from identity.domain.entities import Membership, MembershipStatus
from identity.features.memberships.service import MembershipService
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from datetime import datetime


class FakeMembershipRepo:
    def __init__(self) -> None:
        self.memberships: dict[uuid.UUID, Membership] = {}
        self.created: list[Membership] = []
        self.updated: list[Membership] = []

    def _assign_id(self, membership: Membership) -> Membership:
        if membership.id is None:
            membership.id = uuid.uuid4()
        return membership

    async def create(self, membership: Membership) -> Membership:
        self._assign_id(membership)
        self.memberships[membership.id] = membership
        self.created.append(membership)
        return membership

    async def get_by_id(self, membership_id: str | uuid.UUID) -> Membership | None:
        return self.memberships.get(uuid.UUID(str(membership_id)))

    async def get_by_email(self, tenant_id: str | uuid.UUID, email: str) -> Membership | None:
        for membership in self.memberships.values():
            if membership.invited_email == email.lower() and str(membership.tenant_id) == str(
                tenant_id
            ):
                return membership
        return None

    async def get_by_user(
        self, user_id: str | uuid.UUID, tenant_id: str | uuid.UUID
    ) -> Membership | None:
        for membership in self.memberships.values():
            if str(membership.user_id) == str(user_id) and str(membership.tenant_id) == str(
                tenant_id
            ):
                return membership
        return None

    async def list_by_tenant(
        self,
        tenant_id: str | uuid.UUID,
        *,
        status: MembershipStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Membership]:
        rows = [
            m
            for m in self.memberships.values()
            if str(m.tenant_id) == str(tenant_id) and (status is None or m.status is status)
        ]
        return rows[offset : offset + limit]

    async def update_status(
        self,
        membership_id: str | uuid.UUID,
        *,
        status: MembershipStatus,
        suspended_at: datetime | None = None,
    ) -> Membership:
        membership = self.memberships[uuid.UUID(str(membership_id))]
        membership.status = status
        membership.suspended_at = suspended_at
        self.updated.append(membership)
        return membership

    async def set_user(
        self,
        membership_id: str | uuid.UUID,
        user_id: str | uuid.UUID,
        *,
        joined_at: datetime,
    ) -> Membership:
        membership = self.memberships[uuid.UUID(str(membership_id))]
        membership.user_id = uuid.UUID(str(user_id))
        membership.joined_at = joined_at
        membership.status = MembershipStatus.ACTIVE
        membership.suspended_at = None
        self.updated.append(membership)
        return membership


@pytest.fixture
def repo() -> FakeMembershipRepo:
    return FakeMembershipRepo()


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def service(repo: FakeMembershipRepo) -> MembershipService:
    return MembershipService(repo)


async def _invite(service: MembershipService, *, email: str, tenant_id: uuid.UUID) -> Membership:
    return await service.create_invited(
        tenant_id=tenant_id,
        email=email,
        role_id=uuid.uuid4(),
        invited_by_user_id=uuid.uuid4(),
    )


class TestCreateInvited:
    async def test_creates_invited_membership_reserving_email(
        self, service: MembershipService, repo: FakeMembershipRepo, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        assert membership.id is not None
        assert membership.status is MembershipStatus.INVITED
        assert membership.user_id is None
        assert membership.invited_email == "bob@acme.io"
        assert membership.invited_at is not None
        assert membership.joined_at is None

    async def test_email_is_normalized_to_lowercase(
        self, service: MembershipService, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="Bob@Acme.io", tenant_id=tenant_id)
        assert membership.invited_email == "bob@acme.io"

    async def test_duplicate_email_rejected(
        self, service: MembershipService, repo: FakeMembershipRepo, tenant_id: uuid.UUID
    ) -> None:
        await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        with pytest.raises(ValidationError):
            await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        assert len(repo.created) == 1


class TestActivate:
    async def test_invited_becomes_active_with_user(
        self, service: MembershipService, repo: FakeMembershipRepo, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        user_id = uuid.uuid4()
        activated = await service.activate(membership_id=membership.id, user_id=user_id)

        assert activated.status is MembershipStatus.ACTIVE
        assert activated.user_id == user_id
        assert activated.joined_at is not None
        assert activated.suspended_at is None

    async def test_unknown_membership_raises(self, service: MembershipService) -> None:
        with pytest.raises(NotFoundError):
            await service.activate(membership_id=uuid.uuid4(), user_id=uuid.uuid4())


class TestSuspendReinstate:
    async def test_active_can_be_suspended(
        self, service: MembershipService, repo: FakeMembershipRepo, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        await service.activate(membership_id=membership.id, user_id=uuid.uuid4())

        suspended = await service.suspend(membership_id=membership.id)
        assert suspended.status is MembershipStatus.SUSPENDED
        assert suspended.suspended_at is not None

    async def test_suspended_can_be_reinstated(
        self, service: MembershipService, repo: FakeMembershipRepo, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        await service.activate(membership_id=membership.id, user_id=uuid.uuid4())
        await service.suspend(membership_id=membership.id)

        reinstated = await service.reinstate(membership_id=membership.id)
        assert reinstated.status is MembershipStatus.ACTIVE
        assert reinstated.suspended_at is None

    async def test_invited_cannot_be_suspended(
        self, service: MembershipService, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        with pytest.raises(InvalidTransitionError):
            await service.suspend(membership_id=membership.id)

    async def test_active_cannot_be_reinstated(
        self, service: MembershipService, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        await service.activate(membership_id=membership.id, user_id=uuid.uuid4())
        with pytest.raises(InvalidTransitionError):
            await service.reinstate(membership_id=membership.id)


class TestQueries:
    async def test_list_members_filters_by_status(
        self, service: MembershipService, tenant_id: uuid.UUID
    ) -> None:
        invited = await _invite(service, email="a@acme.io", tenant_id=tenant_id)
        active = await _invite(service, email="b@acme.io", tenant_id=tenant_id)
        await service.activate(membership_id=active.id, user_id=uuid.uuid4())

        invited_rows = await service.list_members(tenant_id, status=MembershipStatus.INVITED)
        active_rows = await service.list_members(tenant_id, status=MembershipStatus.ACTIVE)

        assert [m.id for m in invited_rows] == [invited.id]
        assert [m.id for m in active_rows] == [active.id]

    async def test_get_by_user_and_email(
        self, service: MembershipService, tenant_id: uuid.UUID
    ) -> None:
        membership = await _invite(service, email="bob@acme.io", tenant_id=tenant_id)
        user_id = uuid.uuid4()
        await service.activate(membership_id=membership.id, user_id=user_id)

        by_user = await service.get_by_user(user_id, tenant_id)
        by_email = await service.get_by_email(tenant_id, "bob@acme.io")
        assert by_user is not None and by_user.id == membership.id
        assert by_email is not None and by_email.id == membership.id
