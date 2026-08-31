"""Deterministic follow-up suggestion engine (SKY-61 Part 11).

Generates a templated follow-up draft for a stale CRM entity. The draft is
imprecise — it's a starting point the owner can edit or dismiss — but it's
free, reproducible, and zero-latency (no LLM call).

Follow-up rules (per Q&A decision 1 — deterministic theme):
- **Stale lead** (no activity > 7 days): suggest an email re-engagement.
- **Stale opportunity** (no activity > 7 days): suggest a call/meeting.
- **Near-close opportunity** (expected close < 7 days, no activity): suggest
  an urgent check-in email.
- **Overdue close opportunity**: suggest a rescheduling call.

``confidence`` decays as the entity ages (older = less signal) and rises when
recent activities exist (the entity is being worked, just lightly). Returns
``None`` when the entity is not stale (no suggestion needed).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from ai_agent.features.crm.gateway import ActivityRef, LeadRef, OpportunityRef

# After how many days of inactivity a suggestion is generated.
STALE_AFTER_DAYS = 7

# Near-close threshold: suggest a check-in if expected close is within this
# window and the entity has no activity.
NEAR_CLOSE_DAYS = 7

# No-activity confidence floor (mirrors deal_health pattern).
_NO_ACTIVITY_CONFIDENCE = 0.3


@dataclass(frozen=True, slots=True)
class FollowUpDraft:
    """A generated follow-up suggestion ready to be persisted as pending."""

    entity_type: str
    entity_id: uuid.UUID
    user_id: uuid.UUID
    suggestion_type: str
    draft_content: str
    reasoning: str
    confidence: float


def generate_follow_up(
    *,
    entity_type: str,
    entity: LeadRef | OpportunityRef,
    activities: list[ActivityRef],
    now: datetime,
) -> FollowUpDraft | None:
    """Deterministic follow-up generation. Returns None when the entity is not stale."""
    if not entity.owner_id:
        # No owner to assign the suggestion to; skip silently.
        return None

    if not activities:
        stale_days = (now - entity.created_at).total_seconds() / 86400.0
    else:
        latest = max(a.created_at for a in activities)
        stale_days = (now - latest).total_seconds() / 86400.0

    if stale_days < STALE_AFTER_DAYS:
        return None

    velocity = _engagement_velocity(activities, now=now)
    confidence = _confidence(activities, stale_days)

    if entity_type == "lead":
        return _draft_lead(
            entity=entity,  # type: ignore[arg-type]
            stale_days=stale_days,
            velocity=velocity,
            confidence=confidence,
            now=now,
        )
    if entity_type == "opportunity":
        return _draft_opportunity(
            entity=entity,  # type: ignore[arg-type]
            stale_days=stale_days,
            velocity=velocity,
            confidence=confidence,
            now=now,
        )
    return None


# ---- lead-specific drafting -----------------------------------------------


def _draft_lead(
    *,
    entity: LeadRef,
    stale_days: float,
    velocity: float | None,
    confidence: float,
    now: datetime,
) -> FollowUpDraft:
    label = entity.display_name or "this lead"
    velocity_desc = _velocity_descriptor(velocity)
    draft = (
        f"Hi {label},\n\n"
        f"Just circling back to see how things are progressing. "
        f"We haven't connected in {stale_days:.0f} days — happy to help "
        f"with anything.\n\nBest regards"
    )
    reasoning = (
        f"Lead '{label}' has had no activity for {stale_days:.0f} days"
        + (f" ({velocity_desc})" if velocity_desc else "")
        + ". A brief re-engagement email is the lightest touch to restart the "
        "conversation."
    )
    return FollowUpDraft(
        entity_type="lead",
        entity_id=entity.id,
        user_id=entity.owner_id,  # type: ignore[arg-type]
        suggestion_type="email",
        draft_content=draft,
        reasoning=reasoning,
        confidence=confidence,
    )


# ---- opportunity-specific drafting ----------------------------------------


def _draft_opportunity(
    *,
    entity: OpportunityRef,
    stale_days: float,
    velocity: float | None,
    confidence: float,
    now: datetime,
) -> FollowUpDraft:
    label = entity.display_name or "this deal"
    velocity_desc = _velocity_descriptor(velocity)

    overdue = False
    if entity.expected_close_date is not None:
        close = datetime.combine(entity.expected_close_date, datetime.min.time(), tzinfo=UTC)
        overdue = close < now

    if overdue:
        suggestion_type = "call"
        draft = (
            f"Hi — following up on {label}. "
            f"Our expected close date ({entity.expected_close_date}) has passed "
            f"and we haven't touched base in {stale_days:.0f} days. "
            f"Would you be available for a brief call this week to realign?"
        )
        reasoning = (
            f"Opportunity '{label}' is overdue (expected close "
            f"{entity.expected_close_date}) and stale ({stale_days:.0f} days "
            f"no activity). A rescheduling call is the fastest path to clarity."
        )
    elif entity.expected_close_date is not None:
        close = datetime.combine(entity.expected_close_date, datetime.min.time(), tzinfo=UTC)
        days_until = (close - now).total_seconds() / 86400.0
        if days_until <= NEAR_CLOSE_DAYS and stale_days >= STALE_AFTER_DAYS:
            suggestion_type = "email"
            draft = (
                f"Hi — just checking in ahead of our target close date "
                f"({entity.expected_close_date}) for {label}. "
                f"We haven't connected in {stale_days:.0f} days — "
                f"want to make sure everything is on track."
            )
            reasoning = (
                f"Opportunity '{label}' is {days_until:.0f} days from close "
                f"but has been inactive for {stale_days:.0f} days. A pre-close "
                "check-in reduces the risk of a surprise slip."
            )
        else:
            suggestion_type = "call"
            draft = _default_opp_draft(label, stale_days)
            reasoning = _default_opp_reasoning(label, stale_days, velocity_desc)
    else:
        suggestion_type = "call"
        draft = _default_opp_draft(label, stale_days)
        reasoning = _default_opp_reasoning(label, stale_days, velocity_desc)

    return FollowUpDraft(
        entity_type="opportunity",
        entity_id=entity.id,
        user_id=entity.owner_id,  # type: ignore[arg-type]
        suggestion_type=suggestion_type,
        draft_content=draft,
        reasoning=reasoning,
        confidence=confidence,
    )


def _default_opp_draft(label: str, stale_days: float) -> str:
    return (
        f"Hi — following up on {label}. "
        f"We haven't touched base in {stale_days:.0f} days. "
        f"Would you be open to a quick call to discuss next steps?"
    )


def _default_opp_reasoning(label: str, stale_days: float, velocity_desc: str) -> str:
    return (
        f"Opportunity '{label}' has had no activity for {stale_days:.0f} days"
        + (f" ({velocity_desc})" if velocity_desc else "")
        + ". A call is the fastest way to understand the current state and "
        "determine whether to advance or re-scope."
    )


# ---- helpers ---------------------------------------------------------------


def _engagement_velocity(activities: list[ActivityRef], *, now: datetime) -> float | None:
    """Fraction of all activity in the last 14 days."""
    if not activities:
        return None
    window_start = now - timedelta(days=14)
    recent = sum(1 for a in activities if a.created_at >= window_start)
    return recent / len(activities)


def _velocity_descriptor(velocity: float | None) -> str:
    if velocity is None:
        return "no activity recorded"
    if velocity < 0.5:
        return "engagement is slowing"
    if velocity < 0.8:
        return "engagement is moderate"
    return "engagement is active"


def _confidence(activities: list[ActivityRef], stale_days: float) -> float:
    """0..1 — rises with activity volume, falls with staleness."""
    if not activities:
        return _NO_ACTIVITY_CONFIDENCE
    volume = min(len(activities) / 10.0, 1.0)
    # Staleness penalty: each 7 days beyond the threshold reduces confidence
    # by ~5%, floored at 0.25.
    staleness_penalty = max(0.25, 1.0 - (max(0.0, stale_days - STALE_AFTER_DAYS) / 140.0))
    return round(min(volume * staleness_penalty, 1.0), 2)
