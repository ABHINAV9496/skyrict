"""Rolling demand-profile computation for the restock scan (INV-AI-002).

Pure functions, no I/O: given a product/warehouse's movement window, produce
the demand facts the spec §3.2 enhanced formula needs (average daily demand,
demand CV, observed window length, last receipt) plus the per-SKU
``eligible`` gate. Mirrors the forecast calculator's ledger reading - issues
(``qty < 0``) are demand; receipts are supply - so both features agree on what
"demand" means. The :class:`DemandStats` value object itself lives in
``ai_agent.domain`` (shared with the repository layer).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from ai_agent.domain.demand_stats import DemandStats

if TYPE_CHECKING:
    import uuid

    from ai_agent.features.nl_query.gateway import MovementRow

# The rolling window the scan tracks demand over (days).
_WINDOW_DAYS = 60

# Minimum observed history before a SKU is eligible for the v2 formula.
_MIN_HISTORY_DAYS = 30


def compute_demand_stats(
    *,
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    movements: list[MovementRow],
    window_days: int = _WINDOW_DAYS,
) -> DemandStats:
    """Derive demand stats for one product+warehouse from its movement window.

    Rows are computed for EVERY scanned pair (even zero-history ones) so the
    backfill keeps the stats table complete; ``eligible`` is False until the
    pair has enough observed history AND nonzero average demand.
    """
    now = datetime.now(tz=UTC)
    cutoff = now - timedelta(days=max(window_days, 1))

    relevant = [
        m
        for m in movements
        if m.product_id == product_id
        and m.warehouse_id == warehouse_id
        and _as_utc(m.created_at) >= cutoff
    ]
    if not relevant:
        return DemandStats(
            product_id=product_id,
            warehouse_id=warehouse_id,
            avg_daily_demand=Decimal(0),
            demand_cv=Decimal(0),
            window_days=0,
            last_receipt_at=None,
            eligible=False,
        )

    issues = [m for m in relevant if m.movement_type == "issue" and m.qty < 0]
    receipts = [m for m in relevant if m.movement_type == "receipt" and m.qty > 0]

    oldest = min(_as_utc(m.created_at) for m in relevant)
    span_days = max((now - oldest).days, 1)
    total_demand = sum((abs(m.qty) for m in issues), Decimal(0))
    avg_daily_demand = (
        (total_demand / Decimal(span_days)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if total_demand > 0
        else Decimal(0)
    )

    demand_cv = _coefficient_of_variation(issues)
    last_receipt_at = max(_as_utc(m.created_at) for m in receipts) if receipts else None

    return DemandStats(
        product_id=product_id,
        warehouse_id=warehouse_id,
        avg_daily_demand=avg_daily_demand,
        demand_cv=demand_cv,
        window_days=span_days,
        last_receipt_at=last_receipt_at,
        eligible=span_days >= _MIN_HISTORY_DAYS and avg_daily_demand > 0,
    )


def _coefficient_of_variation(issues: list[MovementRow]) -> Decimal:
    """Stddev / mean over issue quantities; 0 when there is no baseline."""
    quantities = [Decimal(str(abs(m.qty))) for m in issues]
    if len(quantities) < 3:
        return Decimal(0)
    mean = sum(quantities) / Decimal(len(quantities))
    if mean == 0:
        return Decimal(0)
    variance = sum((q - mean) ** 2 for q in quantities) / Decimal(len(quantities))
    sigma = variance.sqrt()
    return (sigma / mean).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
