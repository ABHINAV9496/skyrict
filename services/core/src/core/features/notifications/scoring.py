"""Priority scoring engine (SKY-93) - severity x recency x role relevance.

Pure functions with no I/O: the same inputs always produce the same score,
which keeps the ranking deterministic for tests and for the batching worker.

Score formula:

    score = severity_weight * recency_factor + relevance_boost

- ``severity_weight``: low=10, medium=40, high=70, critical=100.
- ``recency_factor`` decays linearly from 1.0 to a floor of 0.4 over ~4
  hours (``1 - min(0.6, age_hours * 0.15)``): a fresh event ranks far above
  an aging one, but nothing decays to zero.
- ``relevance_boost``: +10 when the recipient's role relevance applies
  (the recipient was resolved through the category's audience - explicit
  targeting or a permission/role grant). Never pushes a low above a medium
  fresh event.

Pinning (the "critical approval-due pins above the fold" rule) is a hard
policy, not an artifact of the score: severity CRITICAL always pins.

``score_priority`` is intentionally a module-level function so unit tests
exercise the exact ranking math without a database.
"""

from __future__ import annotations

from datetime import datetime

from core.features.notifications.domain import (
    SEVERITY_WEIGHTS,
    NotificationSeverity,
)

# Max fraction of the weight a recency decay can remove (floor 0.4x).
_MAX_DECAY = 0.6
# Decay per hour of age: after 1h score keeps ~85%, after 4h it floors.
_DECAY_PER_HOUR = 0.15
# Score boost when the recipient's role relevance applies.
RELEVANCE_BOOST = 10


def _recency_factor(age_hours: float) -> float:
    """Recency multiplier: 1.0 when fresh, floor 0.4 after ~4 hours."""
    decay = min(_MAX_DECAY, age_hours * _DECAY_PER_HOUR)
    return max(1.0 - _MAX_DECAY, 1.0 - decay)


def score_priority(
    *,
    severity: NotificationSeverity,
    now: datetime,
    occurred_at: datetime,
    relevant: bool = False,
) -> int:
    """Return the 0-100 priority score for one notification.

    Args:
        severity: the event severity.
        now: the scoring clock (injectable for tests).
        occurred_at: when the event happened.
        relevant: True when the recipient's role relevance applies.

    Returns:
        An integer in [0, 100]. A fresh critical is 100; a fresh low with a
        relevance boost is 20; an aging low stays well below any medium.
    """
    age_hours = max(0.0, (now - occurred_at).total_seconds()) / 3600.0
    score = SEVERITY_WEIGHTS[severity] * _recency_factor(age_hours)
    if relevant:
        score += RELEVANCE_BOOST
    return max(0, min(100, round(score)))


def is_pinned(severity: NotificationSeverity) -> bool:
    """Whether the notification pins to the top of the inbox.

    Hard policy: critical severity pins. Everything else renders in score
    order below the pins.
    """
    return severity == NotificationSeverity.CRITICAL
