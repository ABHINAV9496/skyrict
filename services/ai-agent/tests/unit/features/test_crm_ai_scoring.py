"""Unit tests for the deterministic lead scoring engine (SKY-61).

The engine is a pure, time-immutable function: tests construct a fixed ``now``
and assert exact band behaviour and the factor breakdown, not LLM outputs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ai_agent.features.crm.gateway import ActivityRef, LeadRef
from ai_agent.features.crm.scoring import (
    BEHAVIOR_WEIGHT,
    ENGAGEMENT_WEIGHT,
    FIT_WEIGHT,
    RECENCY_WEIGHT,
    STAGE_AGE_WEIGHT,
    score_lead,
)

LEAD_ID = uuid.uuid4()
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def _lead(**overrides: object) -> LeadRef:
    base: dict[str, object] = {
        "id": LEAD_ID,
        "status": "new",
        "source": "website",
        "created_at": NOW - timedelta(days=2),
        "owner_id": None,
        "has_name": True,
        "has_email": True,
    }
    base.update(overrides)
    return LeadRef(**base)  # type: ignore[arg-type]


def _activity(days_ago: int = 0, *, completed: bool = True) -> ActivityRef:
    return ActivityRef(
        id=uuid.uuid4(),
        kind="call",
        completed_at=NOW - timedelta(days=days_ago) if completed else None,
        created_at=NOW - timedelta(days=days_ago),
    )


class TestWeights:
    def test_weights_sum_to_one(self) -> None:
        total = ENGAGEMENT_WEIGHT + FIT_WEIGHT + BEHAVIOR_WEIGHT + RECENCY_WEIGHT + STAGE_AGE_WEIGHT
        assert total == pytest.approx(1.0)

    def test_weights_match_the_decided_formula(self) -> None:
        assert ENGAGEMENT_WEIGHT == 0.25
        assert FIT_WEIGHT == 0.20
        assert BEHAVIOR_WEIGHT == 0.20
        assert RECENCY_WEIGHT == 0.20
        assert STAGE_AGE_WEIGHT == 0.15


class TestScoreBounds:
    def test_score_is_within_0_100_and_is_an_integer(self) -> None:
        result = score_lead(
            lead=_lead(), activities=[_activity(days_ago=1), _activity(days_ago=3)], now=NOW
        )
        assert 0 <= result.score <= 100
        assert isinstance(result.score, int)

    def test_no_activity_lead_scores_low_with_low_confidence(self) -> None:
        result = score_lead(lead=_lead(created_at=NOW - timedelta(days=60)), activities=[], now=NOW)
        assert result.score < 50
        assert result.confidence == 0.3

    def test_engagement_concentrated_lead_scores_high(self) -> None:
        activities = [_activity(days_ago=i) for i in range(10)]
        result = score_lead(lead=_lead(), activities=activities, now=NOW)
        assert result.score >= 85


class TestFactorBreakdown:
    def test_factors_carry_weights_in_order(self) -> None:
        result = score_lead(lead=_lead(), activities=[_activity(days_ago=1)], now=NOW)
        assert len(result.factors) == 5
        assert "engagement" in result.factors[0]
        assert "fit" in result.factors[1]
        assert "behavior" in result.factors[2]
        assert "recency" in result.factors[3]
        assert "stage age" in result.factors[4]
        assert "0.25" in result.factors[0]

    def test_factor_scores_are_explainable_human_readable(self) -> None:
        result = score_lead(lead=_lead(), activities=[_activity(days_ago=1)], now=NOW)
        for factor in result.factors:
            assert factor == factor.lower()
            assert "x" in factor


class TestDeterminism:
    def test_same_inputs_yield_same_score(self) -> None:
        lead = _lead()
        activities = [_activity(days_ago=1), _activity(days_ago=4)]
        first = score_lead(lead=lead, activities=activities, now=NOW)
        second = score_lead(lead=lead, activities=activities, now=NOW)
        assert first.score == second.score
        assert first.confidence == second.confidence
        assert first.factors == second.factors

    def test_recency_decay_prefers_fresh_activity(self) -> None:
        fresh = score_lead(lead=_lead(), activities=[_activity(days_ago=1)], now=NOW)
        stale = score_lead(lead=_lead(), activities=[_activity(days_ago=60)], now=NOW)
        assert fresh.score > stale.score


class TestConfidence:
    def test_more_activity_signal_raises_confidence(self) -> None:
        low = score_lead(lead=_lead(), activities=[_activity(days_ago=1)], now=NOW)
        high = score_lead(
            lead=_lead(), activities=[_activity(days_ago=i) for i in range(10)], now=NOW
        )
        assert high.confidence > low.confidence
        assert high.confidence <= 1.0

    def test_contact_completeness_boosts_confidence(self) -> None:
        sparse_lead = _lead(has_name=False, has_email=False)
        with_contact = _lead(has_name=True)
        sparse = score_lead(lead=sparse_lead, activities=[_activity(days_ago=1)], now=NOW)
        complete = score_lead(lead=with_contact, activities=[_activity(days_ago=1)], now=NOW)
        assert complete.confidence > sparse.confidence
