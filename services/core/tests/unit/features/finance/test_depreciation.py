"""Unit tests for fixed assets & depreciation engine (FIN-AUT-004, SKY-85 B13/B28).

Covers asset CRUD, depreciation accrual (half-year convention, cap at salvage),
and the idempotent run-period contract. Repository persistence tested by
integration suites.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from core.core.audit_events import (
    FINANCE_DEPRECIATION_RUN,
    FINANCE_FIXED_ASSET_CREATED,
)
from core.domain.value_objects import FixedAssetStatus
from core.features.finance.depreciation import FinanceDepreciationService
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from core.domain.entities import DepreciationEntry, FixedAsset


class StubAssetRepo:
    def __init__(self) -> None:
        self.assets: dict[uuid.UUID, FixedAsset] = {}
        self.entries: list[DepreciationEntry] = []
        self._entry_index: dict[tuple[uuid.UUID, str], DepreciationEntry] = {}

    async def create_fixed_asset(self, asset: FixedAsset) -> FixedAsset:
        aid = uuid.uuid4()
        stored = replace(asset, id=aid)
        self.assets[aid] = stored
        return stored

    async def get_fixed_asset(self, asset_id: uuid.UUID, tenant_id: uuid.UUID) -> FixedAsset | None:
        a = self.assets.get(asset_id)
        return a if a is not None and a.tenant_id == tenant_id else None

    async def list_fixed_assets(
        self, tenant_id: uuid.UUID, *, status: str | None = None
    ) -> list[FixedAsset]:
        values = [a for a in self.assets.values() if a.tenant_id == tenant_id]
        if status is not None:
            values = [a for a in values if a.status == status]
        return values

    async def update_fixed_asset(self, asset: FixedAsset) -> FixedAsset | None:
        if asset.id is None or asset.id not in self.assets:
            return None
        self.assets[asset.id] = asset
        return asset

    async def create_depreciation_entry(self, entry: DepreciationEntry) -> DepreciationEntry:
        eid = uuid.uuid4()
        stored = replace(entry, id=eid)
        self.entries.append(stored)
        self._entry_index[(entry.asset_id, entry.period)] = stored
        return stored

    async def get_depreciation_entry(
        self, asset_id: uuid.UUID, period: str, tenant_id: uuid.UUID
    ) -> DepreciationEntry | None:
        return self._entry_index.get((asset_id, period))

    async def list_depreciation_entries(
        self, tenant_id: uuid.UUID, *, period: str | None = None
    ) -> list[DepreciationEntry]:
        if period is not None:
            return [e for e in self.entries if e.period == period]
        return list(self.entries)


class StubLedger:
    def __init__(self) -> None:
        self.accounts: dict[str, Any] = {}
        self.entries: list[Any] = []

    async def get_account_by_code(self, code: str, tenant_id: uuid.UUID):
        return self.accounts.get(code)

    async def create_journal_entry(self, entry: Any) -> Any:
        self.entries.append(entry)
        return SimpleNamespace(id=uuid.uuid4())


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


TENANT = uuid.uuid4()
USER = uuid.uuid4()
ACCT_EXPENSE = "5100"
ACCT_CONTRA = "1700"


def _fresh() -> tuple[StubAssetRepo, StubLedger, RecordingAudit, FinanceDepreciationService]:
    repo = StubAssetRepo()
    ledger = StubLedger()
    ledger.accounts[ACCT_EXPENSE] = SimpleNamespace(id=uuid.uuid4())
    ledger.accounts[ACCT_CONTRA] = SimpleNamespace(id=uuid.uuid4())
    audit = RecordingAudit()
    return repo, ledger, audit, FinanceDepreciationService(repo=repo, ledger=ledger, audit=audit)


def _body(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "name": "Server",
        "cost": Decimal("12000"),
        "acquisition_date": date(2025, 1, 15),
        "useful_life_years": 5,
        "category": "IT",
        "depreciation_method": "straight_line",
        "salvage_value": Decimal("0"),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def test_create_asset() -> None:
    _repo, _ledger, audit, svc = _fresh()
    asset = await svc.create_asset(TENANT, USER, _body())
    assert asset.id is not None
    assert asset.name == "Server"
    assert asset.status == FixedAssetStatus.ACTIVE
    assert audit.logs[-1]["action"] == FINANCE_FIXED_ASSET_CREATED


async def test_get_asset_not_found() -> None:
    _, _, _, svc = _fresh()
    with pytest.raises(NotFoundError):
        await svc.get_asset(TENANT, uuid.uuid4())


async def test_update_asset_rejects_non_active() -> None:
    _repo, _ledger, _, svc = _fresh()
    asset = await svc.create_asset(TENANT, USER, _body())
    await svc.dispose(TENANT, USER, asset.id, date(2026, 1, 1))
    with pytest.raises(ValidationError, match="Only active"):
        await svc.update_asset(TENANT, USER, asset.id, _body(name="New"))


async def test_dispose_rejects_before_acquisition() -> None:
    _repo, _ledger, _, svc = _fresh()
    asset = await svc.create_asset(TENANT, USER, _body())
    with pytest.raises(ValidationError, match="cannot precede"):
        await svc.dispose(TENANT, USER, asset.id, date(2024, 1, 1))


async def test_dispose_rejects_already_disposed() -> None:
    _repo, _ledger, _, svc = _fresh()
    asset = await svc.create_asset(TENANT, USER, _body())
    await svc.dispose(TENANT, USER, asset.id, date(2026, 6, 1))
    with pytest.raises(ValidationError, match="already disposed"):
        await svc.dispose(TENANT, USER, asset.id, date(2026, 6, 1))


async def test_run_period_books_draft_journal() -> None:
    repo, ledger, audit, svc = _fresh()
    asset = await svc.create_asset(
        TENANT, USER, _body(cost=Decimal("12000"), useful_life_years=4, salvage_value=Decimal("0"))
    )
    result = await svc.run_period(TENANT, USER, "2025-01")
    assert result.entries_created == 1
    assert result.total_amount == Decimal("125.00")
    assert len(ledger.entries) == 1
    je = ledger.entries[0]
    assert je.source == "depreciation"
    assert je.source_ref == f"{asset.id}:2025-01"
    assert audit.logs[-1]["action"] == FINANCE_DEPRECIATION_RUN
    assert repo.assets[asset.id].accumulated_depreciation == Decimal("125.00")


async def test_run_period_skips_existing() -> None:
    _repo, ledger, _audit, svc = _fresh()
    await svc.create_asset(TENANT, USER, _body(cost=Decimal("12000"), useful_life_years=4))
    first = await svc.run_period(TENANT, USER, "2025-01")
    second = await svc.run_period(TENANT, USER, "2025-01")
    assert first.entries_created == 1
    assert second.entries_skipped >= 1
    assert second.entries_created == 0
    assert len(ledger.entries) == 1


async def test_half_year_convention_acquisition_year() -> None:
    """Acquisition year accrues 50% of annual; subsequent years full 1/12."""
    _repo, _ledger, _, svc = _fresh()
    await svc.create_asset(
        TENANT,
        USER,
        _body(cost=Decimal("120000"), useful_life_years=10, salvage_value=Decimal("0")),
    )
    # Full year: annual = 120000/10 = 12000, monthly = 1000
    # Acquisition year (half): 6000/12 = 500
    r = await svc.run_period(TENANT, USER, "2025-06")
    assert r.total_amount == Decimal("500.00")
    # Subsequent year
    r2 = await svc.run_period(TENANT, USER, "2026-01")
    assert r2.total_amount == Decimal("1000.00")


async def test_depreciation_caps_at_salvage() -> None:
    repo, _ledger, _, svc = _fresh()
    asset = await svc.create_asset(
        TENANT,
        USER,
        _body(cost=Decimal("1000"), useful_life_years=1, salvage_value=Decimal("800")),
    )
    result = await svc.run_period(TENANT, USER, "2025-06")
    # annual = (1000-800)/1 = 200; half-year = 100/12 = 8.33
    assert result.total_amount == Decimal("8.33")
    updated = repo.assets[asset.id]
    assert updated.status == FixedAssetStatus.ACTIVE


async def test_run_period_missing_account_raises() -> None:
    _repo, ledger, _, svc = _fresh()
    ledger.accounts.pop(ACCT_EXPENSE)
    await svc.create_asset(TENANT, USER, _body())
    with pytest.raises(ValidationError, match="account codes"):
        await svc.run_period(TENANT, USER, "2025-01")


async def test_run_period_skips_pre_acquisition_periods() -> None:
    _repo, _ledger, _, svc = _fresh()
    await svc.create_asset(TENANT, USER, _body())
    result = await svc.run_period(TENANT, USER, "2024-06")
    assert result.entries_created == 0
    assert result.entries_skipped >= 1
