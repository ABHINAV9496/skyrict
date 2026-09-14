"""Deterministic CRM pipeline anomaly rules (SKY-91).

The scheduled scan runs every rule over each OPEN opportunity's refs and
activity rows and persists whatever fires. Rules are pure functions so they
are exhaustively unit-testable; the scan service only orchestrates. Per
FIN-AI-003, anomaly decisions are **deterministic** - no LLM output ever
decides what is anomalous, so the same data always produces the same
findings.

Rules (see the AI-CRM-Sales-Integration module spec Part 13):

1. ``activity_bulk``            - 5+ activities on one deal in 24h       warning
2. ``missing_next_activity``    - no activity at all (critical) or the
                                 last activity is 14+ days old (warning)
3. ``stage_stall``              - 30+ days in stage with the close date
                                 passed (critical) or due inside 30 days
                                 or unset (warning)

Thresholds are module constants so the scan can tune them without touching
rule logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from ai_agent.features.crm.gateway import ActivityRef, OpportunityRef

# Rule identifiers - persisted verbatim in ``ai_crm_anomalies.rule_id``.
RULE_ACTIVITY_BULK = "activity_bulk"
RULE_MISSING_NEXT_ACTIVITY = "missing_next_activity"
RULE_STAGE_STALL = "stage_stall"

# Thresholds (SKY-91 Part 13).
_ACTIVITY_BULK_THRESHOLD = 5  # >= 5 activities within the window is a burst.
_ACTIVITY_BULK_WINDOW_HOURS = 24
_STALE_AFTER_DAYS = 14  # no activity for 14+ days means the deal went quiet.
_STAGE_STALL_DAYS = 30  # 30+ days without a stage move is a stall.
_STAGE_STALL_CLOSE_WINDOW_DAYS = 30  # stall matters when close is due inside 30 days.
_SEVERITIES = frozenset({"critical", "warning", "info"})


@dataclass(frozen=True, slots=True)
class CrmAnomalyFinding:
    """One detection result, ready for persistence in ``ai_crm_anomalies``."""

    rule_id: str
    severity: str
    title: str
    description: str
    opportunity_id: uuid.UUID
    context: dict[str, object] | None = None


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def detect_all(
    *,
    opportunity: OpportunityRef,
    activities: list[ActivityRef],
) -> list[CrmAnomalyFinding]:
    """Run every SKY-91 rule for one open opportunity.

    The scan calls this per open deal; findings are the rows to persist.
    """
    findings: list[CrmAnomalyFinding] = []
    findings.extend(detect_activity_bulk(opportunity.id, activities))
    findings.extend(detect_missing_next_activity(opportunity.id, activities))
    findings.extend(detect_stage_stall(opportunity=opportunity))
    return findings


def detect_activity_bulk(
    opportunity_id: uuid.UUID, activities: list[ActivityRef]
) -> list[CrmAnomalyFinding]:
    """5+ activities on one deal inside 24 hours (warning).

    A burst of activity rows (calls, meetings, emails, notes) in a single
    window suggests bulk back-filling, an import, or bot-driven entries
    rather than organic sales motion. Deterministic and thresholded - the
    LLM never decides what counts as a burst.
    """
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(hours=_ACTIVITY_BULK_WINDOW_HOURS)
    burst = [
        activity
        for activity in activities
        if activity.created_at is not None and _as_utc(activity.created_at) >= cutoff
    ]
    if len(burst) < _ACTIVITY_BULK_THRESHOLD:
        return []
    return [
        CrmAnomalyFinding(
            rule_id=RULE_ACTIVITY_BULK,
            severity="warning",
            title=f"Activity burst: {len(burst)} in {_ACTIVITY_BULK_WINDOW_HOURS}h",
            description=(
                f"{len(burst)} activities were recorded on this deal within the "
                f"last {_ACTIVITY_BULK_WINDOW_HOURS} hours - possible bulk "
                f"back-fill or imported history."
            ),
            opportunity_id=opportunity_id,
            context={"count": len(burst), "window_hours": _ACTIVITY_BULK_WINDOW_HOURS},
        )
    ]


def detect_missing_next_activity(
    opportunity_id: uuid.UUID, activities: list[ActivityRef]
) -> list[CrmAnomalyFinding]:
    """An open deal with nothing on the timeline (critical) or gone quiet (warning).

    A deal with no recorded activity at all has no visible next step -
    critical while it stays open. A deal whose most recent activity is 14+
    days old has silently idled - warning. Recency is measured on
    ``created_at`` (the actual recorded moment, not completion time). The
    scan only runs this on open deals, so a won/lost deal is never flagged.
    """
    if not activities:
        return [
            CrmAnomalyFinding(
                rule_id=RULE_MISSING_NEXT_ACTIVITY,
                severity="critical",
                title="No activity on this deal",
                description=(
                    "The deal has no recorded activities - there is no visible "
                    "next step on its timeline."
                ),
                opportunity_id=opportunity_id,
                context={"days_since_last_activity": None},
            )
        ]

    dated = [activity.created_at for activity in activities if activity.created_at is not None]
    if not dated:
        return []  # every activity lacks a timestamp; cannot judge recency.
    latest = _as_utc(max(dated))
    days_since = (datetime.now(tz=UTC) - latest).days
    if days_since < _STALE_AFTER_DAYS:
        return []
    return [
        CrmAnomalyFinding(
            rule_id=RULE_MISSING_NEXT_ACTIVITY,
            severity="warning",
            title=f"No activity for {days_since} days",
            description=(
                f"The most recent activity on this deal is {days_since} days old - "
                f"the deal has gone quiet with no next step in sight."
            ),
            opportunity_id=opportunity_id,
            context={"days_since_last_activity": days_since},
        )
    ]


def detect_stage_stall(*, opportunity: OpportunityRef) -> list[CrmAnomalyFinding]:
    """A deal stuck in one stage whose close date is at risk.

    A deal is stalled when it has not moved stage for ``_STAGE_STALL_DAYS``
    (core's ``last_stage_change_at`` is the stage-move proxy). The stall is
    only anomalous when it threatens the close: the expected close date is
    unset, due inside ``_STAGE_STALL_CLOSE_WINDOW_DAYS`` days, or already
    passed. A deliberately long-lived stage with a far-away close date is not
    flagged. Past-close stalls are critical; imminent/unset-close stalls are
    warning.
    """
    now = datetime.now(tz=UTC)
    last_move = _as_utc(opportunity.last_stage_change_at)
    days_in_stage = (now - last_move).days
    if days_in_stage < _STAGE_STALL_DAYS:
        return []

    close = opportunity.expected_close_date
    if close is None:
        return [
            CrmAnomalyFinding(
                rule_id=RULE_STAGE_STALL,
                severity="warning",
                title=f"Deal stuck in '{opportunity.stage}' for {days_in_stage} days",
                description=(
                    f"The deal has not moved stage in {days_in_stage} days and has "
                    f"no expected close date - the close is effectively unplanned."
                ),
                opportunity_id=opportunity.id,
                context={
                    "stage": opportunity.stage,
                    "days_in_stage": days_in_stage,
                    "days_to_close": None,
                },
            )
        ]

    days_to_close = (close - now.date()).days
    if days_to_close > _STAGE_STALL_CLOSE_WINDOW_DAYS:
        return []  # stalled but the close date is far out - not yet anomalous.
    severity = "critical" if days_to_close < 0 else "warning"
    return [
        CrmAnomalyFinding(
            rule_id=RULE_STAGE_STALL,
            severity=severity,
            title=f"Deal stuck in '{opportunity.stage}' for {days_in_stage} days",
            description=(
                f"The deal has not moved stage in {days_in_stage} days and its "
                f"expected close date of {close.isoformat()} is "
                f"{'already past' if days_to_close < 0 else f'{days_to_close} days away'}."
            ),
            opportunity_id=opportunity.id,
            context={
                "stage": opportunity.stage,
                "days_in_stage": days_in_stage,
                "days_to_close": days_to_close,
            },
        )
    ]


def valid_severity(severity: str) -> bool:
    """True when the value is one of the CRM anomaly severities."""
    return severity in _SEVERITIES
