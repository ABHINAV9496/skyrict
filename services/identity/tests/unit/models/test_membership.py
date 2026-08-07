"""Unit tests for the membership entity and ORM model.

Covers the MembershipStatus enum, Membership entity defaults and lifecycle
guards, and the memberships table shape exposed through the canonical ORM
metadata (so model, registry, and migration stay in agreement).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from identity.domain.entities import Membership, MembershipStatus
from identity.models.base import Base


class TestMembershipStatus:
    def test_lifecycle_values(self):
        assert MembershipStatus.INVITED.value == "invited"
        assert MembershipStatus.ACTIVE.value == "active"
        assert MembershipStatus.SUSPENDED.value == "suspended"

    def test_lifecycle_has_no_duplicates(self):
        values = [status.value for status in MembershipStatus]
        assert len(values) == len(set(values))


class TestMembershipEntity:
    def test_active_defaults(self):
        membership = Membership(tenant_id=2, user_id=1)
        assert membership.status is MembershipStatus.ACTIVE
        assert membership.role_id is None
        assert membership.invited_by_user_id is None
        assert membership.joined_at is None
        assert membership.suspended_at is None
        assert membership.id is None

    def test_invited_membership_has_no_user(self):
        invited = Membership(
            tenant_id=2,
            invited_email="bob@acme.io",
            status=MembershipStatus.INVITED,
            role_id=3,
            invited_by_user_id=4,
            invited_at=datetime.now(UTC),
        )
        assert invited.status is MembershipStatus.INVITED
        assert invited.user_id is None
        assert invited.invited_email == "bob@acme.io"
        assert invited.role_id == 3
        assert invited.invited_by_user_id == 4
        assert invited.joined_at is None

    def test_membership_without_user_or_email_is_rejected(self):
        with pytest.raises(ValueError):
            Membership(tenant_id=2, user_id=None, invited_email=None)

    def test_active_membership_without_user_is_rejected(self):
        with pytest.raises(ValueError):
            Membership(tenant_id=2, invited_email="bob@acme.io", status=MembershipStatus.ACTIVE)


class TestMembershipModelMetadata:
    def test_model_registered_in_canonical_registry(self):
        import identity.models  # noqa: F401

        assert "memberships" in Base.metadata.tables

    def test_tenant_scoped_columns(self):
        columns = set(Base.metadata.tables["memberships"].columns.keys())
        assert {"user_id", "tenant_id", "invited_email", "role_id", "status"} <= columns

    def test_user_id_is_nullable_for_invited(self):
        column = Base.metadata.tables["memberships"].columns["user_id"]
        assert column.nullable is True

    def test_status_column_uses_membership_enum(self):
        column = Base.metadata.tables["memberships"].columns["status"]
        assert column.type.name == "membership_status"

    def test_unique_constraints(self):
        constraints = Base.metadata.tables["memberships"].constraints
        names = {constraint.name for constraint in constraints}
        assert {"uq_memberships_user_tenant", "uq_memberships_tenant_email"} <= names

    def test_user_or_email_check_constraint(self):
        constraints = Base.metadata.tables["memberships"].constraints
        names = {constraint.name for constraint in constraints}
        assert "ck_memberships_user_or_email" in names

    def test_timestamps_present(self):
        columns = set(Base.metadata.tables["memberships"].columns.keys())
        assert {"created_at", "updated_at", "joined_at", "invited_at", "suspended_at"} <= columns
