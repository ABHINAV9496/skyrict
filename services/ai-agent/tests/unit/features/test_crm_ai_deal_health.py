"""Unit tests for the deterministic deal-health engine (SKY-61).

Pure and time-immutable: tests inject a fixed ``now`` and assert on the health
band, the exact risk/action lists, and the deterministic aggregates
(engagement_velocity, days_in_stage).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from ai_agent.features.crm.deal_health import (
    OpportunitySignals,
    assess_deal_health,
)
from ai_agent.features.crm.gateway import ActivityRef

OPP_ID = uuid.uuid4()
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def _signals(**overrides: object) -> OpportunitySignals:
    base: dict[str, object] = {
        "opportunity_id": OPP_ID,
        "stage": "negotiation",
        "probability": 80,
        "has_amount": True,
        "created_at": NOW - timedelta(days=20),
        "last_stage_change_at": NOW - timedelta(days=5),
        "expected_close_date": date(2026, 9, 15),
    }
    base.update(overrides)
    return OpportunitySignals(**base)  # type: ignore[arg-type]


def _activity(days_ago: int = 0, *, completed: bool = True) -> ActivityRef:
    return ActivityRef(
        id=uuid.uuid4(),
        kind="meeting",
        completed_at=NOW - timedelta(days=days_ago) if completed else None,
        created_at=NOW - timedelta(days=days_ago),
    )


class TestHealthyDeal:
    def test_active_deal_in_stage_scores_green(self) -> None:
        result = assess_deal_health(
            signals=_signals(),
            activities=[_activity(days_ago=2), _activity(days_ago=6)],
            now=NOW,
        )
        assert result.health == "green"
        assert result.risk_factors == []
        assert result.recommended_actions == []
        assert result.engagement_velocity == 1.0
        assert result.days_in_stage == 5


class TestBandSignals:
    def test_stale_deal_is_yellow(self) -> None:
        result = assess_deal_health(
            signals=_signals(),
            activities=[_activity(days_ago=30)],
            now=NOW,
        )
        assert result.health == "yellow"
        assert any("no activity" in risk for risk in result.risk_factors)
        assert any("re-engage" in action for action in result.recommended_actions)

    def test_no_activity_deal_is_risky_and_low_confidence(self) -> None:
        result = assess_deal_health(signals=_signals(), activities=[], now=NOW)
        assert result.health == "red"
        assert result.confidence == 0.3
        assert any("touchpoint" in action for action in result.recommended_actions)

    def test_stuck_in_stage_flags_risk(self) -> None:
        result = assess_deal_health(
            signals=_signals(last_stage_change_at=NOW - timedelta(days=40)),
            activities=[_activity(days_ago=2)],
            now=NOW,
        )
        assert result.health == "yellow"
        assert any("stuck" in risk for risk in result.risk_factors)
        assert result.days_in_stage == 40

    def test_overdue_close_date_flags_risk(self) -> None:
        result = assess_deal_health(
            signals=_signals(expected_close_date=date(2026, 8, 1)),
            activities=[_activity(days_ago=2)],
            now=NOW,
        )
        assert any("close date has passed" in risk for risk in result.risk_factors)
        assert any("close date" in action for action in result.recommended_actions)

    def test_low_probability_deal_flags_risk(self) -> None:
        result = assess_deal_health(
            signals=_signals(probability=15),
            activities=[_activity(days_ago=2)],
            now=NOW,
        )
        assert any("win probability" in risk for risk in result.risk_factors)

    def test_missing_amount_flags_risk(self) -> None:
        result = assess_deal_health(
            signals=_signals(has_amount=False),
            activities=[_activity(days_ago=2)],
            now=NOW,
        )
        assert any("no deal value" in risk for risk in result.risk_factors)
        assert any("expected deal amount" in action for action in result.recommended_actions)


class TestVelocity:
    def test_slowing_velocity_flags_risk_and_reports_fraction(self) -> None:
        # 4 total activities but only 1 within the last 14 days.
        activities = [_activity(days_ago=1)] + [_activity(days_ago=20) for _ in range(3)]
        result = assess_deal_health(signals=_signals(), activities=activities, now=NOW)
        assert result.engagement_velocity == 0.25
        assert any("slowing" in risk for risk in result.risk_factors)
        assert result.health == "yellow"


class TestConfidence:
    def test_more_signal_raises_confidence(self) -> None:
        low = assess_deal_health(signals=_signals(), activities=[_activity(days_ago=2)], now=NOW)
        high = assess_deal_health(
            signals=_signals(), activities=[_activity(days_ago=i) for i in range(10)], now=NOW
        )
        assert high.confidence > low.confidence
        assert high.confidence <= 1.0

    def test_missing_amount_lowers_confidence(self) -> None:
        with_value = assess_deal_health(
            signals=_signals(), activities=[_activity(days_ago=2)], now=NOW
        )
        without_value = assess_deal_health(
            signals=_signals(has_amount=False), activities=[_activity(days_ago=2)], now=NOW
        )
        assert with_value.confidence > without_value.confidence


class TestDeterminism:
    def test_same_inputs_yield_same_band(self) -> None:
        first = assess_deal_health(signals=_signals(), activities=[_activity(days_ago=2)], now=NOW)
        second = assess_deal_health(signals=_signals(), activities=[_activity(days_ago=2)], now=NOW)
        assert first.health == second.health
        assert first.risk_factors == second.risk_factors
        assert first.recommended_actions == second.recommended_actions
