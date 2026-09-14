"""Unit tests for the priority scoring engine (SKY-93).

Pure math, no I/O: these encode the ranking contract the drawer and the
batching window rely on - severity dominates, recency decays to a floor, a
relevance boost never flips severity tiers, and only critical pins.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.features.notifications.domain import NotificationSeverity
from core.features.notifications.scoring import is_pinned, score_priority

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _age(now: datetime, hours: float) -> datetime:
    return now - timedelta(hours=hours)


class TestScorePriority:
    def test_fresh_critical_is_100(self) -> None:
        assert (
            score_priority(
                severity=NotificationSeverity.CRITICAL,
                now=NOW,
                occurred_at=NOW,
            )
            == 100
        )

    def test_fresh_high_is_70(self) -> None:
        assert (
            score_priority(
                severity=NotificationSeverity.HIGH,
                now=NOW,
                occurred_at=NOW,
            )
            == 70
        )

    def test_fresh_medium_is_40(self) -> None:
        assert (
            score_priority(
                severity=NotificationSeverity.MEDIUM,
                now=NOW,
                occurred_at=NOW,
            )
            == 40
        )

    def test_fresh_low_with_relevance_boost_is_20(self) -> None:
        assert (
            score_priority(
                severity=NotificationSeverity.LOW,
                now=NOW,
                occurred_at=NOW,
                relevant=True,
            )
            == 20
        )

    def test_relevance_boost_never_pushes_low_above_medium(self) -> None:
        low_fresh = score_priority(
            severity=NotificationSeverity.LOW,
            now=NOW,
            occurred_at=NOW,
            relevant=True,
        )
        medium_fresh = score_priority(
            severity=NotificationSeverity.MEDIUM,
            now=NOW,
            occurred_at=NOW,
        )
        assert low_fresh < medium_fresh

    def test_recency_decays_but_never_below_floor(self) -> None:
        aged = score_priority(
            severity=NotificationSeverity.HIGH,
            now=NOW,
            occurred_at=_age(NOW, 10.0),
        )
        # floor = 0.4 * 70 = 28
        assert aged == 28
        very_old = score_priority(
            severity=NotificationSeverity.HIGH,
            now=NOW,
            occurred_at=_age(NOW, 100.0),
        )
        assert very_old == 28

    def test_one_hour_age_keeps_85_percent(self) -> None:
        score = score_priority(
            severity=NotificationSeverity.HIGH,
            now=NOW,
            occurred_at=_age(NOW, 1.0),
        )
        assert score == round(70 * 0.85)

    def test_future_occurred_at_never_ages(self) -> None:
        score = score_priority(
            severity=NotificationSeverity.HIGH,
            now=NOW,
            occurred_at=_age(NOW, -5.0),
        )
        assert score == 70

    def test_score_stays_in_0_100_bounds(self) -> None:
        for severity in NotificationSeverity:
            s = score_priority(
                severity=severity,
                now=NOW,
                occurred_at=NOW,
                relevant=True,
            )
            assert 0 <= s <= 100


class TestIsPinned:
    def test_only_critical_pins(self) -> None:
        assert is_pinned(NotificationSeverity.CRITICAL)
        assert not is_pinned(NotificationSeverity.HIGH)
        assert not is_pinned(NotificationSeverity.MEDIUM)
        assert not is_pinned(NotificationSeverity.LOW)
