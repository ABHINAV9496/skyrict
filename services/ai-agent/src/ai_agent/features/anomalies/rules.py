"""Anomaly detection rules - deterministic checks over recent movements.

Each rule takes the fetched movement window plus reference data and returns
zero or more :class:`AnomalyFinding` objects. Rules are pure functions so
they are exhaustively unit-testable; the service only orchestrates.

Deferred rules (need data core does not expose yet - documented, not
forgotten):
- transfer_without_receipt / stock_level_mismatch: need the full ledger and
  stock-level snapshots per movement (core exposes neither).
- reorder_alert_ignored: needs alert history with timestamps.
- negative_adjustment_spike: partially covered by unusual_adjustment_size;
  a dedicated frequency window needs a longer movement horizon than the
  gateway's page-capped fetch guarantees.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from ai_agent.features.nl_query.gateway import MovementRow

# Spec §4.2 thresholds.
_DROP_WINDOW_HOURS = 48
_DROP_RATIO = Decimal("0.5")  # >50% drop within the window is High severity.
_ADJUSTMENT_SIGMA_FACTOR = Decimal(3)  # >3x standard deviation is Medium.
_MIN_ADJUSTMENT_BASELINE = 4  # stddev over fewer adjustments is noise
_OFF_HOUR_START = 0  # local-hour window [0, 6) counts as off-hours.
_OFF_HOUR_END = 6
_SEVERITIES = {"low", "medium", "high", "critical"}


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    """One detection result, ready for persistence."""

    anomaly_type: str
    severity: str
    title: str
    description: str
    affected_product_id: uuid.UUID | None
    affected_warehouse_id: uuid.UUID | None
    related_movement_ids: list[uuid.UUID] = field(default_factory=list)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def detect_all(movements: list[MovementRow]) -> list[AnomalyFinding]:
    """Run every v1 rule over the movement window."""
    findings: list[AnomalyFinding] = []
    findings.extend(detect_sudden_drops(movements))
    findings.extend(detect_unusual_adjustments(movements))
    findings.extend(detect_duplicate_refs(movements))
    findings.extend(detect_off_hours(movements))
    return findings


def detect_sudden_drops(movements: list[MovementRow]) -> list[AnomalyFinding]:
    """>50% of a product's recent inflow vanished via issues/adjustments in 48h."""
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(hours=_DROP_WINDOW_HOURS)
    by_product: dict[uuid.UUID, list[MovementRow]] = defaultdict(list)
    for m in movements:
        if (
            m.movement_type in ("receipt", "issue", "adjustment")
            and _as_utc(m.created_at) >= cutoff
        ):
            by_product[m.product_id].append(m)

    findings: list[AnomalyFinding] = []
    for product_id, rows in by_product.items():
        inflow = sum((m.qty for m in rows if m.qty > 0), Decimal(0))
        outflow = abs(sum((m.qty for m in rows if m.qty < 0), Decimal(0)))
        if inflow <= 0 or outflow / inflow <= _DROP_RATIO:
            continue
        involved = sorted(m.id for m in rows if m.qty < 0)
        findings.append(
            AnomalyFinding(
                anomaly_type="sudden_stock_drop",
                severity="high",
                title=f"Sudden stock drop for product {product_id}",
                description=(
                    f"{outflow} units left against {inflow} received "
                    f"within {_DROP_WINDOW_HOURS} hours."
                ),
                affected_product_id=product_id,
                affected_warehouse_id=rows[-1].warehouse_id,
                related_movement_ids=involved,
            )
        )
    return findings


def detect_unusual_adjustments(movements: list[MovementRow]) -> list[AnomalyFinding]:
    """Adjustments larger than 3x the stddev of the OTHER adjustments.

    The baseline is computed leave-one-out: a single huge outlier inflates
    its own baseline so much that it could otherwise never exceed
    mean + 3*sigma (the max achievable z-score in a sample of n is
    (n-1)/sqrt(n) < 3). Comparing each adjustment against the statistics of
    the remaining window is the statistically sound reading of the spec's
    ">3x standard deviation" rule (spec §4.2).
    """
    adjustment_rows = [m for m in movements if m.movement_type == "adjustment"]
    if len(adjustment_rows) < _MIN_ADJUSTMENT_BASELINE:
        return []  # stddev over a handful of points is noise

    findings: list[AnomalyFinding] = []
    for i, candidate in enumerate(adjustment_rows):
        others = [abs(m.qty) for j, m in enumerate(adjustment_rows) if j != i]
        if len(others) < _MIN_ADJUSTMENT_BASELINE - 1:
            continue
        mean = sum(others, Decimal(0)) / len(others)
        sigma = Decimal(str(statistics.stdev(float(a) for a in others)))
        threshold = mean + sigma * _ADJUSTMENT_SIGMA_FACTOR
        size = abs(candidate.qty)
        if size <= threshold:
            continue
        findings.append(
            AnomalyFinding(
                anomaly_type="unusual_adjustment_size",
                severity="medium",
                title=f"Unusual adjustment size ({size} units)",
                description=(
                    f"Adjustment of {size} exceeds {threshold:.2f} "
                    f"(peer mean {mean:.2f} + {_ADJUSTMENT_SIGMA_FACTOR}x std dev)."
                ),
                affected_product_id=candidate.product_id,
                affected_warehouse_id=candidate.warehouse_id,
                related_movement_ids=[candidate.id],
            )
        )
    return findings


def detect_duplicate_refs(movements: list[MovementRow]) -> list[AnomalyFinding]:
    """Same ref_id posted more than once for the same warehouse (spec: High)."""
    refs_by_wh: dict[tuple[uuid.UUID, str], list[MovementRow]] = defaultdict(list)
    for m in movements:
        if m.ref_id:
            refs_by_wh[(m.warehouse_id, str(m.ref_id))].append(m)

    findings: list[AnomalyFinding] = []
    for (_wh, ref_id), rows in refs_by_wh.items():
        if len(rows) < 2:
            continue
        findings.append(
            AnomalyFinding(
                anomaly_type="duplicate_movement_ref",
                severity="high",
                title=f"Duplicate movement reference '{ref_id}'",
                description=(
                    f"Reference '{ref_id}' appears {len(rows)} times at warehouse "
                    f"{rows[0].warehouse_id} - possible double-posting."
                ),
                affected_product_id=rows[0].product_id,
                affected_warehouse_id=rows[0].warehouse_id,
                related_movement_ids=[m.id for m in rows],
            )
        )
    return findings


def detect_off_hours(movements: list[MovementRow]) -> list[AnomalyFinding]:
    """Movements between midnight and early morning are Low severity."""
    findings: list[AnomalyFinding] = []
    for m in movements:
        hour = _as_utc(m.created_at).hour
        if not (_OFF_HOUR_START <= hour < _OFF_HOUR_END):
            continue
        findings.append(
            AnomalyFinding(
                anomaly_type="off_hours_movement",
                severity="low",
                title=f"Off-hours movement ({_as_utc(m.created_at):%H:%M} UTC)",
                description=(
                    f"{m.movement_type} of {m.qty} recorded outside business hours "
                    f"at warehouse {m.warehouse_id}."
                ),
                affected_product_id=m.product_id,
                affected_warehouse_id=m.warehouse_id,
                related_movement_ids=[m.id],
            )
        )
    return findings


def valid_severity(severity: str) -> bool:
    """True when the value is one of the spec §4.2 severities."""
    return severity in _SEVERITIES
