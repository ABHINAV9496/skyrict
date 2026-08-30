"""Minimal 5-field cron matcher for payroll schedules (HR-AUT-001 §5.8).

The platform has no generic scheduler; this is the payroll-automation-only
recurrence matcher. It supports the classic five fields

    minute  (0-59)  hour  (0-23)  day-of-month  (1-31)  month  (1-12)  dow  (0-6, 0=Sun)

with ``*``, literal values, comma lists (``1,15``) and dash ranges (``1-5``).
No steps (``*/5``), names (``JAN``) or seconds field — out of scope, documented
as an accepted simplification. Standard crontab OR-rule for day-of-month vs
day-of-week: when both are restricted a fire happens when EITHER matches;
when one is ``*`` only the restricted field constrains the day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Way beyond any monthly schedule; guards the matcher against pathological
# expressions that can never fire (e.g. Feb 30).
_MAX_SCAN_DAYS = 400

_LIMITS: tuple[tuple[int, int], ...] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day-of-month
    (1, 12),  # month
    (0, 6),   # day-of-week
)


def _parse_field(raw: str, index: int) -> frozenset[int]:
    lo, hi = _LIMITS[index]
    if raw == "*":
        return frozenset(range(lo, hi + 1))
    values: set[int] = set()
    for part in raw.split(","):
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if not (lo <= start <= end <= hi):
                raise ValueError(f"bad range {part!r} in cron field {index}")
            values.update(range(start, end + 1))
        else:
            value = int(part)
            if not lo <= value <= hi:
                raise ValueError(f"value {value} out of range in cron field {index}")
            values.add(value)
    return frozenset(values)


@dataclass(frozen=True)
class CronExpression:
    """A parsed 5-field cron expression with next-fire computation."""

    expression: str
    minute: frozenset[int]
    hour: frozenset[int]
    day_of_month: frozenset[int]
    month: frozenset[int]
    day_of_week: frozenset[int]

    @property
    def _day_constraint(self) -> bool:
        """True when the day-of-month field is restricted (not ``*``)."""
        return self.day_of_month != frozenset(range(1, 32))

    @property
    def _dow_constraint(self) -> bool:
        return self.day_of_week != frozenset(range(0, 7))

    def matches(self, moment: datetime) -> bool:
        """Whether ``moment`` satisfies this expression."""
        if moment.month not in self.month:
            return False
        dom_matches = moment.day in self.day_of_month
        dow_matches = _py_dow_to_cron(moment.weekday()) in self.day_of_week
        use_dom, use_dow = self._day_constraint, self._dow_constraint
        if use_dom and use_dow:
            if not (dom_matches or dow_matches):
                return False
        elif (use_dom and not dom_matches) or (use_dow and not dow_matches):
            return False
        return moment.hour in self.hour and moment.minute in self.minute

    def next_match_after(self, from_dt: datetime) -> datetime:
        """The earliest ``datetime`` strictly after ``from_dt`` that fires.

        Raises ``ValueError`` when no match exists within the scan horizon
        (an expression that can never fire, e.g. ``0 0 30 2 *``).
        """
        start = from_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for offset in range(_MAX_SCAN_DAYS + 1):
            day = start + timedelta(days=offset)
            if day.month not in self.month:
                continue
            dom_matches = day.day in self.day_of_month
            dow_matches = _py_dow_to_cron(day.weekday()) in self.day_of_week
            use_dom, use_dow = self._day_constraint, self._dow_constraint
            if use_dom and use_dow:
                if not (dom_matches or dow_matches):
                    continue
            elif (use_dom and not dom_matches) or (use_dow and not dow_matches):
                continue
            candidate = datetime(
                day.year,
                day.month,
                day.day,
                0,
                0,
                tzinfo=from_dt.tzinfo,
            )
            if candidate > from_dt and (
                candidate.hour in self.hour and candidate.minute in self.minute
            ):
                return candidate
            for hour in sorted(self.hour):
                if hour < day.hour and offset == 0:
                    continue
                for minute in sorted(self.minute):
                    moment = candidate.replace(hour=hour, minute=minute)
                    if moment > from_dt:
                        return moment
        raise ValueError(
            f"cron expression {self.expression!r} has no next fire within "
            f"{_MAX_SCAN_DAYS} days"
        )


def parse_cron(expression: str) -> CronExpression:
    """Parse + validate a 5-field cron string."""
    fields = expression.strip().split()
    if len(fields) != 5:
        raise ValueError("cron expression must have exactly 5 fields")
    minute, hour, dom, month, dow = fields
    return CronExpression(
        expression=expression.strip(),
        minute=_parse_field(minute, 0),
        hour=_parse_field(hour, 1),
        day_of_month=_parse_field(dom, 2),
        month=_parse_field(month, 3),
        day_of_week=_parse_field(dow, 4),
    )


def _py_dow_to_cron(python_weekday: int) -> int:
    """Translate Python's ``weekday()`` (Mon=0) to cron DOW (Sun=0)."""
    return (python_weekday + 1) % 7


__all__ = ["CronExpression", "parse_cron"]
