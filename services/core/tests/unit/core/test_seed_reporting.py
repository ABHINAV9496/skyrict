"""seed_reporting_defaults unit tests - fake session factory, no database (RPT-DATA-001)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from core.features.reporting.seeds import PHASE_1_REPORT_SEEDS
from core.seed import seed_reporting_defaults

if TYPE_CHECKING:
    import pytest

    from core.features.reporting.models.report_definition import ErpReportDefinitionModel


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakeSession:
    """Record adds/commits and serve canned ``execute`` results."""

    def __init__(self, existing_slugs: list[str] | None = None) -> None:
        self.rows = [(slug,) for slug in (existing_slugs or [])]
        self.added: list[ErpReportDefinitionModel] = []
        self.committed = False

    async def execute(self, stmt: object) -> FakeResult:
        return FakeResult(self.rows)

    def add(self, model: ErpReportDefinitionModel) -> None:
        self.added.append(model)

    async def commit(self) -> None:
        self.committed = True


class FakeFactory:
    """Mimics ``async_sessionmaker()`` used as ``async with``."""

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *exc: object) -> None:
        return None


def _patch_factory(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> None:
    from core import seed as seed_module

    monkeypatch.setattr(seed_module, "async_session_factory", lambda: FakeFactory(session))


class TestSeedReportingDefaults:
    async def test_seeds_full_pack_for_fresh_tenant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = FakeSession()
        _patch_factory(monkeypatch, session)
        tenant = uuid.uuid4()

        await seed_reporting_defaults(tenant)

        assert session.committed
        assert len(session.added) == len(PHASE_1_REPORT_SEEDS)
        by_slug = {model.slug: model for model in session.added}
        assert set(by_slug) == {seed.slug for seed in PHASE_1_REPORT_SEEDS}
        for seed in PHASE_1_REPORT_SEEDS:
            model = by_slug[seed.slug]
            assert model.tenant_id == tenant
            assert model.title == seed.title
            assert model.module == seed.module
            assert model.description == seed.description
            assert model.sql == seed.sql
            assert model.params == list(seed.params)
            assert model.permission_key == seed.permission_key

    async def test_idempotent_when_full_pack_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = FakeSession(existing_slugs=[s.slug for s in PHASE_1_REPORT_SEEDS])
        _patch_factory(monkeypatch, session)

        await seed_reporting_defaults(uuid.uuid4())

        assert session.committed
        assert session.added == []

    async def test_only_inserts_missing_slugs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        existing = {"pnl_by_period", "ar_aging"}
        session = FakeSession(existing_slugs=sorted(existing))
        _patch_factory(monkeypatch, session)

        await seed_reporting_defaults(uuid.uuid4())

        added_slugs = {model.slug for model in session.added}
        assert added_slugs == {s.slug for s in PHASE_1_REPORT_SEEDS} - existing


class TestSeedShapeChecks:
    def test_catalog_reused_is_phase_one(self) -> None:
        # The provisioning hook seeds the SAME pack as migration 0036 - exactly
        # the 12 Phase-1 reports from erp-phase1.md §M-RPT.
        assert {s.slug for s in PHASE_1_REPORT_SEEDS} == {
            "pnl_by_period",
            "ar_aging",
            "cash_received",
            "pipeline_value_by_stage",
            "orders_by_period",
            "top_customers",
            "stock_on_hand_vs_reorder",
            "movement_by_type",
            "slow_movers",
            "headcount_by_department",
            "leave_usage",
            "payroll_cost_by_period",
        }
