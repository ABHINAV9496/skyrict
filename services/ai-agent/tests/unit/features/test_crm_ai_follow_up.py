"""Unit tests for the deterministic follow-up suggestion engine (SKY-61).

The engine is a pure, time-immutable function: tests construct a fixed ``now``
and assert exact suggestion type, draft content patterns, and confidence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from ai_agent.features.crm.follow_up import (
    FollowUpDraft,
    generate_follow_up,
)
from ai_agent.features.crm.gateway import ActivityRef, LeadRef, OpportunityRef

NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
OWNER_ID = uuid.uuid4()


def _lead(
    *,
    days_ago: int = 60,
    owner_id: uuid.UUID | None = OWNER_ID,
    display_name: str | None = "Beta Corp",
) -> LeadRef:
    return LeadRef(
        id=uuid.uuid4(),
        status="new",
        source="website",
        created_at=NOW - timedelta(days=days_ago),
        owner_id=owner_id,
        has_name=True,
        has_email=True,
        display_name=display_name,
    )


def _opportunity(
    *,
    days_ago: int = 60,
    expected_close_days_from_now: int | None = 10,
    owner_id: uuid.UUID | None = OWNER_ID,
) -> OpportunityRef:
    close_date = (
        None
        if expected_close_days_from_now is None
        else (NOW + timedelta(days=expected_close_days_from_now)).date()
    )
    return OpportunityRef(
        id=uuid.uuid4(),
        stage="negotiation",
        probability=70,
        has_amount=True,
        created_at=NOW - timedelta(days=days_ago),
        owner_id=owner_id,
        last_stage_change_at=NOW - timedelta(days=days_ago),
        expected_close_date=close_date,
        display_name="Acme Renewal",
    )


def _activity(days_ago: int = 0) -> ActivityRef:
    return ActivityRef(
        id=uuid.uuid4(),
        kind="call",
        completed_at=NOW - timedelta(days=days_ago),
        created_at=NOW - timedelta(days=days_ago),
    )


class TestStalenessGate:
    def test_fresh_entity_returns_none(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=2)],
            now=NOW,
        )
        assert result is None

    def test_stale_entity_returns_draft(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is not None
        assert isinstance(result, FollowUpDraft)
        assert result.entity_type == "lead"

    def test_no_activity_fresh_lead_returns_none(self) -> None:
        """An entity created today with no activity is not stale yet."""
        fresh = _lead(days_ago=1)
        result = generate_follow_up(
            entity_type="lead",
            entity=fresh,
            activities=[],
            now=NOW,
        )
        assert result is None

    def test_no_activity_old_lead_returns_draft(self) -> None:
        """An entity created long ago with no activity is stale."""
        old = _lead(days_ago=30)
        result = generate_follow_up(
            entity_type="lead",
            entity=old,
            activities=[],
            now=NOW,
        )
        assert result is not None
        assert result.entity_type == "lead"


class TestLeadSuggestions:
    def test_stale_lead_suggests_email(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is not None
        assert result.suggestion_type == "email"

    def test_draft_mentions_entity_label(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(display_name="Acme Inc"),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is not None
        assert "Acme Inc" in result.draft_content

    def test_draft_mentions_staleness_days(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=14)],
            now=NOW,
        )
        assert result is not None
        assert "14 days" in result.draft_content

    def test_no_owner_returns_none(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(owner_id=None),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is None


class TestOpportunitySuggestions:
    def test_stale_opportunity_suggests_call(self) -> None:
        result = generate_follow_up(
            entity_type="opportunity",
            entity=_opportunity(),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is not None
        assert result.suggestion_type == "call"

    def test_overdue_suggests_call(self) -> None:
        result = generate_follow_up(
            entity_type="opportunity",
            entity=_opportunity(expected_close_days_from_now=-3),
            activities=[_activity(days_ago=14)],
            now=NOW,
        )
        assert result is not None
        assert result.suggestion_type == "call"
        assert "overdue" in result.reasoning.lower() or "passed" in result.reasoning.lower()

    def test_near_close_suggests_email(self) -> None:
        result = generate_follow_up(
            entity_type="opportunity",
            entity=_opportunity(expected_close_days_from_now=3),
            activities=[_activity(days_ago=10)],
            now=NOW,
        )
        assert result is not None
        assert result.suggestion_type == "email"
        assert "close" in result.draft_content.lower()

    def test_no_close_date_suggests_call(self) -> None:
        result = generate_follow_up(
            entity_type="opportunity",
            entity=_opportunity(expected_close_days_from_now=None),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is not None
        assert result.suggestion_type == "call"


class TestConfidence:
    def test_no_activity_low_confidence(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(days_ago=30),
            activities=[],
            now=NOW,
        )
        assert result is not None
        assert result.confidence == 0.3

    def test_many_activities_higher_confidence(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=i + 10) for i in range(10)],
            now=NOW,
        )
        assert result is not None
        assert result.confidence > 0.5

    def test_very_stale_has_lower_confidence(self) -> None:
        recent = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=10)],
            now=NOW,
        )
        ancient = generate_follow_up(
            entity_type="lead",
            entity=_lead(),
            activities=[_activity(days_ago=60)],
            now=NOW,
        )
        assert recent is not None and ancient is not None
        assert recent.confidence >= ancient.confidence


class TestReasoning:
    def test_reasoning_mentions_entity_label(self) -> None:
        result = generate_follow_up(
            entity_type="lead",
            entity=_lead(display_name="Widget Co"),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is not None
        assert "Widget Co" in result.reasoning


class TestUnknownEntityType:
    def test_unknown_entity_returns_none(self) -> None:
        result = generate_follow_up(
            entity_type="customer",
            entity=_lead(),  # type: ignore[arg-type]
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result is None
