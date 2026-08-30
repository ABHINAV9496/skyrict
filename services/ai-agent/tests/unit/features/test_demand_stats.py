"""Unit tests for the rolling demand-profile computation (INV-AI-002).

Pins the eligibility gate and the ledger-reading semantics: issues are demand,
receipts are supply, the window is the observed span (capped), and a SKU is
only ``eligible`` with enough history AND nonzero average demand.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ai_agent.features.nl_query.gateway import MovementRow
from ai_agent.features.restock.demand_stats import compute_demand_stats

PRODUCT_ID = uuid.uuid4()
WAREHOUSE_ID = uuid.uuid4()


def _movement(
    days_ago: float,
    *,
    movement_type: str = "issue",
    qty: Decimal = Decimal("-5"),
) -> MovementRow:
    return MovementRow(
        id=uuid.uuid4(),
        product_id=PRODUCT_ID,
        warehouse_id=WAREHOUSE_ID,
        movement_type=movement_type,
        qty=qty,
        created_at=datetime.now(tz=UTC) - timedelta(days=days_ago),
        ref_id=None,
    )


class TestDemandStats:
    def test_no_movements_is_ineligible_with_zero_window(self) -> None:
        stats = compute_demand_stats(product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=[])
        assert stats.eligible is False
        assert stats.window_days == 0
        assert stats.avg_daily_demand == Decimal(0)
        assert stats.last_receipt_at is None

    def test_sufficient_history_with_demand_is_eligible(self) -> None:
        movements = [_movement(day, qty=Decimal("-5")) for day in range(40)]
        stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=movements
        )

        assert stats.eligible is True
        assert stats.window_days == 39
        # 40 issue days x 5 units / 39 observed days = 5.13/day.
        assert stats.avg_daily_demand == Decimal("5.1282")

    def test_short_history_is_not_eligible(self) -> None:
        movements = [_movement(day, qty=Decimal("-5")) for day in range(10)]
        stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=movements
        )

        assert stats.window_days == 9
        assert stats.avg_daily_demand == Decimal("5.5556")
        assert stats.eligible is False  # only 9 days < 30-day minimum

    def test_history_without_demand_is_not_eligible(self) -> None:
        movements = [
            _movement(day, movement_type="receipt", qty=Decimal("50")) for day in range(40)
        ]
        stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=movements
        )

        assert stats.avg_daily_demand == Decimal(0)
        assert stats.eligible is False

    def test_latest_receipt_timestamp_captured(self) -> None:
        movements = [
            _movement(1, movement_type="receipt", qty=Decimal("50")),
            _movement(30, movement_type="receipt", qty=Decimal("50")),
            _movement(5, qty=Decimal("-5")),
            _movement(40, qty=Decimal("-5")),
        ]
        stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=movements
        )

        assert stats.last_receipt_at is not None
        assert stats.eligible is True

    def test_demand_cv_measured_from_issue_volatility(self) -> None:
        # Erratic: alternating 1 and 100-unit issues -> high CV.
        erratic = [
            _movement(day, qty=Decimal("-1") if day % 2 == 0 else Decimal("-100"))
            for day in range(40)
        ]
        stable = [_movement(day, qty=Decimal("-5")) for day in range(40)]
        erratic_stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=erratic
        )
        stable_stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=stable
        )
        assert erratic_stats.demand_cv > stable_stats.demand_cv

    def test_other_pairs_are_excluded(self) -> None:
        other_id = uuid.uuid4()
        movements = [_movement(day) for day in range(40)] + [
            MovementRow(
                id=uuid.uuid4(),
                product_id=other_id,
                warehouse_id=WAREHOUSE_ID,
                movement_type="issue",
                qty=Decimal("-500"),
                created_at=datetime.now(tz=UTC) - timedelta(days=1),
                ref_id=None,
            )
        ]
        stats = compute_demand_stats(
            product_id=PRODUCT_ID, warehouse_id=WAREHOUSE_ID, movements=movements
        )
        assert stats.avg_daily_demand == Decimal("5.1282")
