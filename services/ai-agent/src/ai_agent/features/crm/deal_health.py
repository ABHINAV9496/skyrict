"""Deterministic deal health assessment engine (SKY-61 Part 11).

Like lead scoring (Q&A #1), deal health is a fixed deterministic heuristic --
NOT an LLM call -- so every deal gets a stable, explainable green/yellow/red
band and the UI's risk/action lists are fully reproducible.

Each detected risk carries a severity, and the band is the WORST severity seen:

  CRITICAL (red)   - the deal has no recorded activity at all (a total black
                     box; we cannot judge its health).
  NOTABLE (yellow) - stale (no activity > 14d), engagement velocity slowing,
                     stuck in stage (> 30d), expected close date passed, or a
                     low win probability (< 30%).
  INFO    (green)  - present but not itself unhealthy (e.g. no deal value set);
                     reported as an action, never pushes the band above green.

``confidence`` reflects how much signal the engine had (fewer activities =>
lower confidence, mirroring the lead scorer's behaviour).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from ai_agent.features.crm.gateway import ActivityRef

# Recency/staleness windows (days).
STALE_AFTER_DAYS = 14
ACTIVITY_WINDOW_DAYS = 14
STALE_STAGE_DAYS = 30
LOW_PROBABILITY_THRESHOLD = 30.0

# Severity buckets (name + band weight for ordering).
_CRITICAL = 3  # red
_NOTABLE = 2  # yellow
_INFO = 1  # green

# Opportunities with no activities get low confidence.
_NO_ACTIVITY_CONFIDENCE = 0.3


@dataclass(frozen=True, slots=True)
class OpportunitySignals:
    """The deal fields + stage-freshness the health engine needs."""

    opportunity_id: uuid.UUID
    stage: str
    probability: int
    has_amount: bool
    created_at: datetime
    # Last time the stage moved (core sets updated_at on stage change); used as
    # a deterministic proxy for "days in current stage".
    last_stage_change_at: datetime
    expected_close_date: date | None


@dataclass(frozen=True, slots=True)
class DealHealth:
    """A computed health band with the explainable risk/action lists."""

    health: str  # green | yellow | red
    confidence: float
    risk_factors: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    engagement_velocity: float | None = None
    days_in_stage: int | None = None


def assess_deal_health(
    *,
    signals: OpportunitySignals,
    activities: list[ActivityRef],
    now: datetime,
) -> DealHealth:
    """Deterministic green/yellow/red band from core's opportunity + activities.

    ``now`` is injected for time-immutability; production passes the real clock.
    Activities come from ``list_activities_for_entity`` (already entity-scoped).
    """
    days_in_stage = max(int((now - signals.last_stage_change_at).total_seconds() // 86400), 0)
    velocity = _engagement_velocity(activities, now=now)

    worst = _GREEN_SEVERITY
    factors: list[str] = []
    actions: list[str] = []

    if not activities:
        worst = max(worst, _CRITICAL)
        factors.append("no recorded activity")
        actions.append("log the first touchpoint or outreach")
    else:
        latest = max(activity.created_at for activity in activities)
        stale_days = max((now - latest).total_seconds() / 86400.0, 0.0)
        if stale_days > STALE_AFTER_DAYS:
            worst = max(worst, _NOTABLE)
            factors.append(f"no activity for {stale_days:.0f} days")
            actions.append("re-engage the contact soon")

        if velocity is not None and velocity < 0.5:
            worst = max(worst, _NOTABLE)
            factors.append("engagement velocity is slowing")
            actions.append("schedule a working session to revive momentum")

    if days_in_stage > STALE_STAGE_DAYS:
        worst = max(worst, _NOTABLE)
        factors.append(f"stuck in '{signals.stage}' for {days_in_stage} days")
        actions.append("review and advance or re-scope the stage")

    if signals.expected_close_date is not None:
        close = datetime.combine(signals.expected_close_date, datetime.min.time(), tzinfo=UTC)
        if close < now:
            worst = max(worst, _NOTABLE)
            factors.append("expected close date has passed")
            actions.append("re-confirm the close date with the buyer")

    if signals.probability < LOW_PROBABILITY_THRESHOLD:
        worst = max(worst, _NOTABLE)
        factors.append(f"low win probability ({signals.probability}%)")
        actions.append("qualify next steps and strengthen the value case")

    if not signals.has_amount:
        # Info-only: never pushes the band above green, but surfaces the gap.
        factors.append("no deal value recorded")
        actions.append("capture the expected deal amount")

    health = _band(worst)
    confidence = _confidence(activities, signals)

    return DealHealth(
        health=health,
        confidence=confidence,
        risk_factors=factors,
        recommended_actions=actions,
        engagement_velocity=velocity,
        days_in_stage=days_in_stage,
    )


_GREEN_SEVERITY = _INFO  # green (info) is the floor
_BAND_BY_SEVERITY = {_INFO: "green", _NOTABLE: "yellow", _CRITICAL: "red"}


def _band(severity: int) -> str:
    return _BAND_BY_SEVERITY[severity]


def _engagement_velocity(activities: list[ActivityRef], *, now: datetime) -> float | None:
    """Fraction of all activity that happened within the recent window."""
    if not activities:
        return None
    window_start = now - timedelta(days=ACTIVITY_WINDOW_DAYS)
    recent = sum(1 for activity in activities if activity.created_at >= window_start)
    return recent / len(activities)


def _confidence(activities: list[ActivityRef], signals: OpportunitySignals) -> float:
    """0..1 - how much signal the engine had to judge the deal."""
    if not activities:
        return _NO_ACTIVITY_CONFIDENCE
    volume = min(len(activities) / 10.0, 1.0)
    stage_bonus = 0.15 if signals.has_amount else 0.0
    return round(min(volume + stage_bonus, 1.0), 2)
