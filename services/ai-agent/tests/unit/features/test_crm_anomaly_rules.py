"""Unit tests for CRM pipeline anomaly rules (SKY-91).

Pure functions, no DB. Each rule is tested relative to real time (the
functions call ``datetime.now(UTC)`` internally, matching the inventory-
anomaly convention); the test helper ``_now()`` returns the current UTC
time with zero microseconds so boundary calculations are crisp.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from ai_agent.features.anomalies.crm_rules import (
    RULE_ACTIVITY_BULK,
    RULE_MISSING_NEXT_ACTIVITY,
    RULE_STAGE_STALL,
    detect_activity_bulk,
    detect_all,
    detect_missing_next_activity,
    detect_stage_stall,
)
from ai_agent.features.crm.gateway import ActivityRef, OpportunityRef


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _opp(**kwargs: object) -> OpportunityRef:
    now = _now()
    defaults = {
        "id": uuid.uuid4(),
        "stage": "proposal",
        "probability": 40,
        "has_amount": True,
        "created_at": now - timedelta(days=60),
        "owner_id": uuid.uuid4(),
        "last_stage_change_at": now - timedelta(days=50),
        "expected_close_date": date.today() + timedelta(days=30),
    }
    defaults.update(kwargs)  # type: ignore[arg-type]
    return OpportunityRef(**defaults)  # type: ignore[arg-type]


def _activity(created_at: object) -> ActivityRef:
    return ActivityRef(
        id=uuid.uuid4(),
        kind="call",
        completed_at=created_at,
        created_at=created_at,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# detect_activity_bulk
# ---------------------------------------------------------------------------
class TestDetectActivityBulk:
    def test_below_threshold_returns_empty(self) -> None:
        now = _now()
        activities = [_activity(now - timedelta(hours=1)) for _ in range(4)]
        assert detect_activity_bulk(uuid.uuid4(), activities) == []

    def test_exactly_at_threshold_fires(self) -> None:
        now = _now()
        oid = uuid.uuid4()
        activities = [_activity(now - timedelta(hours=1)) for _ in range(5)]
        findings = detect_activity_bulk(oid, activities)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == RULE_ACTIVITY_BULK
        assert f.severity == "warning"
        assert f.opportunity_id == oid
        assert f.context == {"count": 5, "window_hours": 24}

    def test_activities_outside_window_ignored(self) -> None:
        now = _now()
        old = [_activity(now - timedelta(hours=30)) for _ in range(6)]
        assert detect_activity_bulk(uuid.uuid4(), old) == []

    def test_boundary_just_outside_window_returns_empty(self) -> None:
        now = _now()
        assert (
            detect_activity_bulk(
                uuid.uuid4(),
                [_activity(now - timedelta(hours=25)) for _ in range(5)],
            )
            == []
        )


# ---------------------------------------------------------------------------
# detect_missing_next_activity
# ---------------------------------------------------------------------------
class TestDetectMissingNextActivity:
    def test_zero_activities_fires_critical(self) -> None:
        oid = uuid.uuid4()
        findings = detect_missing_next_activity(oid, [])
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == RULE_MISSING_NEXT_ACTIVITY
        assert f.severity == "critical"
        assert f.opportunity_id == oid

    def test_stale_activity_fires_warning(self) -> None:
        now = _now()
        oid = uuid.uuid4()
        activities = [_activity(now - timedelta(days=20))]
        findings = detect_missing_next_activity(oid, activities)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "warning"
        assert f.context == {"days_since_last_activity": 20}

    def test_recent_activity_returns_empty(self) -> None:
        now = _now()
        activities = [_activity(now - timedelta(days=5))]
        assert detect_missing_next_activity(uuid.uuid4(), activities) == []

    def test_boundary_14_days_exactly_fires(self) -> None:
        now = _now()
        activities = [_activity(now - timedelta(days=14))]
        findings = detect_missing_next_activity(uuid.uuid4(), activities)
        assert len(findings) == 1
        assert findings[0].severity == "warning"


# ---------------------------------------------------------------------------
# detect_stage_stall
# ---------------------------------------------------------------------------
class TestDetectStageStall:
    def test_not_staged_long_enough_returns_empty(self) -> None:
        now = _now()
        opp = _opp(last_stage_change_at=now - timedelta(days=29))
        assert detect_stage_stall(opportunity=opp) == []

    def test_stalled_with_passed_close_fires_critical(self) -> None:
        now = _now()
        opp = _opp(
            last_stage_change_at=now - timedelta(days=45),
            expected_close_date=(now - timedelta(days=5)).date(),
        )
        findings = detect_stage_stall(opportunity=opp)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_id == RULE_STAGE_STALL
        assert f.severity == "critical"
        assert f.context["days_in_stage"] == 45
        assert f.context["days_to_close"] < 0

    def test_stalled_with_imminent_close_fires_warning(self) -> None:
        now = _now()
        opp = _opp(
            last_stage_change_at=now - timedelta(days=35),
            expected_close_date=(now + timedelta(days=9)).date(),
        )
        findings = detect_stage_stall(opportunity=opp)
        assert len(findings) == 1
        assert findings[0].severity == "warning"
        assert findings[0].context["days_to_close"] == 9

    def test_stalled_with_far_close_returns_empty(self) -> None:
        now = _now()
        opp = _opp(
            last_stage_change_at=now - timedelta(days=35),
            expected_close_date=(now + timedelta(days=180)).date(),
        )
        assert detect_stage_stall(opportunity=opp) == []

    def test_stalled_with_no_close_date_fires_warning(self) -> None:
        now = _now()
        opp = _opp(
            last_stage_change_at=now - timedelta(days=60),
            expected_close_date=None,
        )
        findings = detect_stage_stall(opportunity=opp)
        assert len(findings) == 1
        assert findings[0].severity == "warning"
        assert findings[0].context["days_to_close"] is None

    def test_boundary_30_days_exactly_fires(self) -> None:
        now = _now()
        opp = _opp(last_stage_change_at=now - timedelta(days=30))
        findings = detect_stage_stall(opportunity=opp)
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# detect_all orchestrator
# ---------------------------------------------------------------------------
class TestDetectAll:
    def test_runs_all_relevant_rules(self) -> None:
        now = _now()
        opp = _opp(
            last_stage_change_at=now - timedelta(days=50),
            expected_close_date=(now - timedelta(days=1)).date(),
        )
        # No activities → missing_next_activity (critical) + stage_stall
        # (critical, close passed). activity_bulk does not fire.
        findings = detect_all(opportunity=opp, activities=[])
        rule_ids = {f.rule_id for f in findings}
        assert RULE_MISSING_NEXT_ACTIVITY in rule_ids
        assert RULE_STAGE_STALL in rule_ids
        assert RULE_ACTIVITY_BULK not in rule_ids
