"""Deterministic lead scoring engine (SKY-61 Part 11).

Deliberate design decision (Q&A #1): scoring is a fixed weighted formula, NOT
an LLM call. This gives every sales rep a stable, explainable, cost-free score
and keeps the "why this score?" factor breakdown entirely reproducible.

Weights (sum = 1.0):
  engagement 0.25  - activity volume + on-time completion
  fit        0.20  - lead source quality + contact completeness
  behavior   0.20  - completed (vs. left-pending) activity depth
  recency    0.20  - how recently the lead engaged (exponential decay)
  stage age  0.15  - how fresh the lead stage assignment is

Each sub-score is a deterministic 0-100 value; the final score is the weighted
sum clamped to [0, 100]. ``confidence`` reflects how much signal core had to
offer (0 when the lead has no activities at all) so the UI can de-emphasise
near-empty scores rather than trusting them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from ai_agent.features.crm.gateway import ActivityRef, LeadRef

# Fixed formula weights (Q&A #1). Kept as module constants so tests and the ADR
# can reference the exact values without magic numbers in the engine.
ENGAGEMENT_WEIGHT = 0.25
FIT_WEIGHT = 0.20
BEHAVIOR_WEIGHT = 0.20
RECENCY_WEIGHT = 0.20
STAGE_AGE_WEIGHT = 0.15

_SCORE_CAP = 100.0

# External default for "no recency/stage signal" so a brand-new or inactive
# lead does not zero-out a band that depends on time.
_RECENCY_FULL_DAYS = 7.0
_RECENCY_HALF_LIFE_DAYS = 14.0
_STAGE_AGE_FULL_DAYS = 7.0
_STAGE_AGE_HALF_LIFE_DAYS = 21.0

# Lead sources treated as high-intent. Everything else gets a neutral score so
# unknown/new sources are never penalised into the ground.
_HIGH_INTENT_SOURCES = {"referral", "website", "event"}


@dataclass(frozen=True, slots=True)
class LeadScore:
    """A computed score with the factor breakdown the UI shows on hover."""

    score: int
    confidence: float
    factors: list[str] = field(default_factory=list)


def score_lead(*, lead: LeadRef, activities: list[ActivityRef], now: datetime) -> LeadScore:
    """Deterministic weighted lead score from core's CRM data.

    ``now`` is injected so tests are time-immutable; production passes the
    real clock. Activities are expected from ``list_activities_for_entity``
    (already entity-scoped by the gateway).
    """
    engagement = _engagement_score(activities)
    fit = _fit_score(lead)
    behavior = _behavior_score(activities)
    recency = _recency_score(activities, now=now)
    stage_age = _stage_age_score(lead, now=now)

    raw = (
        engagement * ENGAGEMENT_WEIGHT
        + fit * FIT_WEIGHT
        + behavior * BEHAVIOR_WEIGHT
        + recency * RECENCY_WEIGHT
        + stage_age * STAGE_AGE_WEIGHT
    )
    score = round(_clamp(raw, _SCORE_CAP))
    confidence = _confidence(activities, lead)

    factors = [
        f"engagement {round(engagement)} x {ENGAGEMENT_WEIGHT}",
        f"fit {round(fit)} x {FIT_WEIGHT}",
        f"behavior {round(behavior)} x {BEHAVIOR_WEIGHT}",
        f"recency {round(recency)} x {RECENCY_WEIGHT}",
        f"stage age {round(stage_age)} x {STAGE_AGE_WEIGHT}",
    ]
    return LeadScore(score=score, confidence=confidence, factors=factors)


def _engagement_score(activities: list[ActivityRef]) -> float:
    """Activity volume, capped at 10 activities for a full score."""
    if not activities:
        return 0.0
    return min(len(activities) * 10.0, _SCORE_CAP)


def _fit_score(lead: LeadRef) -> float:
    """Source intent (50) + contact completeness (50)."""
    source = (lead.source or "").lower()
    source_component = 50.0 if source in _HIGH_INTENT_SOURCES else 25.0
    contact = 25.0 if lead.has_name else 0.0
    contact += 25.0 if lead.has_email else 0.0
    return source_component + contact


def _behavior_score(activities: list[ActivityRef]) -> float:
    """Weight completed activities over merely-created ones."""
    if not activities:
        return 0.0
    completed = sum(1 for activity in activities if activity.completed_at is not None)
    ratio = completed / len(activities)
    # Volume (0-50) + completion ratio (0-50).
    return min(len(activities) * 5.0, 50.0) + ratio * 50.0


def _recency_score(activities: list[ActivityRef], *, now: datetime) -> float:
    """Exponential decay from the most recent activity; full at <=7 days."""
    if not activities:
        return 0.0
    latest = max(activity.created_at for activity in activities)
    age_days = max((now - latest).total_seconds() / 86400.0, 0.0)
    if age_days <= _RECENCY_FULL_DAYS:
        return _SCORE_CAP
    # After the full window, decay with a 14-day half-life past that point.
    return _SCORE_CAP * math.exp(
        -math.log(2) * (age_days - _RECENCY_FULL_DAYS) / _RECENCY_HALF_LIFE_DAYS
    )


def _stage_age_score(lead: LeadRef, *, now: datetime) -> float:
    """Freshness of the lead record; full at <=7 days, decays after."""
    age_days = max((now - lead.created_at).total_seconds() / 86400.0, 0.0)
    if age_days <= _STAGE_AGE_FULL_DAYS:
        return _SCORE_CAP
    return _SCORE_CAP * math.exp(
        -math.log(2) * (age_days - _STAGE_AGE_FULL_DAYS) / _STAGE_AGE_HALF_LIFE_DAYS
    )


def _confidence(activities: list[ActivityRef], lead: LeadRef) -> float:
    """0..1 - how much signal the engine had. No activities => low confidence."""
    if not activities:
        return 0.3
    base = min(len(activities) / 10.0, 1.0)
    contact_bonus = 0.15 if lead.has_name or lead.has_email else 0.0
    return round(min(base + contact_bonus, 1.0), 2)


def _clamp(value: float, cap: float) -> float:
    return max(0.0, min(value, cap))
