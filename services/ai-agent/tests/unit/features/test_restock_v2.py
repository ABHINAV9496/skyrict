"""Unit tests for the v2 enhanced restock formula and scan wiring (INV-AI-002).

Covers the spec §3.2 enhanced formula (avg daily demand * lead time * safety
factor), the eligibility gate that keeps ineligible pairs on the v1 heuristic,
and the feature-flag gate in the scan service (v2 only when the tenant opted in
via ``ai_restock_settings.v2_enabled``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from ai_agent.features.nl_query.gateway import MovementRow, ProductRef, StockLevelRow
from ai_agent.features.restock.calculator import DemandProfile, compute_suggestion
from ai_agent.features.restock.service import RestockService

PRODUCT_ID = uuid.uuid4()
WAREHOUSE_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()


def _product(cost: Decimal | None = Decimal("100.00")) -> ProductRef:
    return ProductRef(
        id=PRODUCT_ID,
        sku="LAPTOP-CHG-001",
        name="Laptop Charger 65W",
        reorder_point=Decimal(10),
        cost_price=cost,
    )


def _demand(
    *,
    avg: Decimal = Decimal("5.0000"),
    eligible: bool = True,
    lead_time: Decimal = Decimal("7.00"),
    safety: Decimal = Decimal("1.000"),
) -> DemandProfile:
    return DemandProfile(
        avg_daily_demand=avg,
        eligible=eligible,
        lead_time_days=lead_time,
        safety_factor=safety,
    )


class TestV2Formula:
    def test_v2_quantity_accounts_for_demand_over_lead_time(self) -> None:
        # 10 (reorder) + 5/day * 7 days * 1.0 - 3 (on hand) = 42.
        draft = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
            demand=_demand(),
        )
        assert draft.suggested_qty == Decimal("42.00")
        assert draft.estimated_cost == Decimal("4200.00")

    def test_v2_clamps_to_zero_at_or_above_target(self) -> None:
        # 10 + 5*7 - 45 = 0 -> nothing to order.
        draft = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(45),
            demand=_demand(),
        )
        assert draft.suggested_qty == Decimal("0.00")

    def test_safety_factor_scales_the_order(self) -> None:
        base = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
            demand=_demand(safety=Decimal("1.000")),
        )
        buffered = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
            demand=_demand(safety=Decimal("1.500")),
        )
        assert buffered.suggested_qty == Decimal("59.50")  # 10 + 5*7*1.5 - 3
        assert buffered.suggested_qty > base.suggested_qty

    def test_v2_reason_reports_demand_and_lead_time(self) -> None:
        draft = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
            demand=_demand(),
        )
        assert "below reorder point" in draft.reason.lower()
        assert "avg daily demand: 5.0000" in draft.reason.lower()
        assert "lead time: 7.00 day(s)" in draft.reason.lower()

    def test_ineligible_profile_falls_back_to_v1(self) -> None:
        draft = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
            demand=_demand(eligible=False),
        )
        assert draft.suggested_qty == Decimal(20)  # reorder_point * 2 heuristic
        assert "avg daily demand" not in draft.reason.lower()

    def test_no_profile_uses_v1(self) -> None:
        draft = compute_suggestion(
            product=_product(),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
        )
        assert draft.suggested_qty == Decimal(20)

    def test_v2_with_missing_cost_yields_null_estimate(self) -> None:
        draft = compute_suggestion(
            product=_product(cost=None),
            warehouse_id=WAREHOUSE_ID,
            qty_on_hand=Decimal(3),
            demand=_demand(),
        )
        assert draft.estimated_cost is None


def _movements_for_scan() -> list[MovementRow]:
    """40 days of -5/day issues: eligible (39d span, 5/day demand)."""
    return [
        MovementRow(
            id=uuid.uuid4(),
            product_id=PRODUCT_ID,
            warehouse_id=WAREHOUSE_ID,
            movement_type="issue",
            qty=Decimal("-5"),
            created_at=datetime.now(tz=UTC) - timedelta(days=day),
            ref_id=None,
        )
        for day in range(40)
    ]


class FakeGateway:
    def __init__(self, *, movements: list[MovementRow]) -> None:
        self._movements = movements
        self.products = [_product()]
        self.stock = [
            StockLevelRow(
                product_id=PRODUCT_ID,
                warehouse_id=WAREHOUSE_ID,
                qty_on_hand=Decimal(3),
                qty_reserved=Decimal(0),
            )
        ]

    async def list_products(self):
        return self.products

    async def get_stock_levels(self, *, product_id=None, warehouse_id=None):
        return self.stock

    async def list_movements(self, *, product_id=None, warehouse_id=None, movement_type=None):
        return self._movements


class FakeSuggestions:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def list_by_status(self, *, tenant_id, status="pending", limit=100):
        return [], 0

    async def create_pending(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs, id=uuid.uuid4())


class FakeAudit:
    async def log(self, *, action, **kwargs):
        pass


class FakeSettings:
    def __init__(self, *, v2_enabled: bool, lead_time: Decimal = Decimal("7.00")) -> None:
        self._v2_enabled = v2_enabled
        self._lead_time = lead_time
        self.rows_created = 0

    async def get_or_create_default(self, *, tenant_id):
        self.rows_created += 1
        return SimpleNamespace(
            v2_enabled=self._v2_enabled,
            lead_time_days=self._lead_time,
            safety_factor=Decimal("1.000"),
        )


class FakeStats:
    def __init__(self) -> None:
        self.upserted: list[object] = []

    async def upsert(self, *, tenant_id, stats):
        self.upserted.append(stats)


def _make_service(*, v2_enabled: bool = False, wired: bool = True):
    gateway = FakeGateway(movements=_movements_for_scan())
    suggestions = FakeSuggestions()
    audit = FakeAudit()

    async def factory():
        return gateway

    settings = FakeSettings(v2_enabled=v2_enabled) if wired else None
    stats = FakeStats() if wired else None
    service = RestockService(
        gateway_factory=factory,
        suggestions=suggestions,
        audit=audit,
        settings=settings,  # type: ignore[arg-type]
        stats=stats,  # type: ignore[arg-type]
    )
    return service, suggestions, settings, stats


class TestScanV2:
    async def test_v2_enabled_uses_backfill_and_enhanced_formula(self) -> None:
        service, repo, _settings, stats = _make_service(v2_enabled=True)
        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.created == 1
        assert len(stats.upserted) == 1  # backfill persisted the profile
        created = repo.created[0]
        # reorder 10 + (200/39 day demand) * 7d lead * 1.0 safety - 3 on hand
        # = 10 + 5.1282*7 - 3 = 42.8974 -> rounds to 42.90.
        assert created["suggested_qty"] == Decimal("42.90")

    async def test_v2_disabled_keeps_v1_heuristic(self) -> None:
        service, repo, _settings, stats = _make_service(v2_enabled=False)
        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.created == 1
        assert stats.upserted == []  # no backfill when the flag is off
        assert repo.created[0]["suggested_qty"] == Decimal(20)

    async def test_unwired_service_stays_on_v1(self) -> None:
        service, repo, _settings, _stats = _make_service(wired=False)
        report = await service.run_scan(tenant_id=TENANT_ID)

        assert report.created == 1
        assert repo.created[0]["suggested_qty"] == Decimal(20)
