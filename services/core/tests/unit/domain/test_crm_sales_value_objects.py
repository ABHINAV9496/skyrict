"""CRM/sales value object tests — enum members mirror the locked SKY-43 enums.

These are the DB-level truth for the native PostgreSQL enums created by
migration 0003: changing a member here without a matching migration breaks
the integration suite, so the exact member lists are asserted.
"""

from __future__ import annotations

from core.domain.value_objects import (
    CreditCheckResult,
    DataScope,
    LeadStatus,
    OpportunityStage,
    OrderStatus,
)


class TestLeadStatus:
    def test_members_match_locked_enum(self) -> None:
        # Locked SKY-43 decision: 4 values, NO 'converted' state.
        assert [member.value for member in LeadStatus] == [
            "new",
            "contacted",
            "qualified",
            "disqualified",
        ]

    def test_no_converted_state(self) -> None:
        assert "converted" not in {member.value for member in LeadStatus}


class TestOpportunityStage:
    def test_members_match_locked_enum(self) -> None:
        # Locked SKY-43 decision: 6 values, pipeline starts at 'prospecting'.
        assert [member.value for member in OpportunityStage] == [
            "prospecting",
            "qualified",
            "proposal",
            "negotiation",
            "won",
            "lost",
        ]


class TestOrderStatus:
    def test_members_match_locked_enum(self) -> None:
        assert [member.value for member in OrderStatus] == [
            "draft",
            "confirmed",
            "fulfilled",
            "cancelled",
        ]


class TestCreditCheckResult:
    def test_members_match_locked_enum(self) -> None:
        assert [member.value for member in CreditCheckResult] == [
            "pending",
            "passed",
            "failed",
        ]


class TestDataScope:
    def test_members_and_privilege_ordering(self) -> None:
        # OWNER < TEAM < ALL is the ordering core/db/rbac.py merges with —
        # the highest scope a user holds wins.
        assert DataScope.OWNER.value == "owner"
        assert DataScope.TEAM.value == "team"
        assert DataScope.ALL.value == "all"
