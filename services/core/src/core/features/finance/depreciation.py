"""Finance fixed assets & depreciation engine (FIN-AUT-004, SKY-85 B13/B28).

Thin service + router for the capital asset register and the idempotent
monthly depreciation run. Each run iterates ACTIVE assets, computes the
straight-line accrual for the period (half-year convention in the acquisition
year), and books a **DRAFT** journal entry stamped ``source='depreciation'`` +
``source_ref=f"{asset_id}:{period}"`` so the journal UNIQUE lock keeps every
``(asset, period)`` exactly-once across replayed runs. Drafts ride the normal
approval path - nothing is posted automatically.

Reads use ``erp.asset.read``; writes use ``erp.asset.write``; the run uses
``erp.asset.run``.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_finance_depreciation_service,
    require_permission,
)
from core.core.audit_events import (
    FINANCE_DEPRECIATION_RUN,
    FINANCE_FIXED_ASSET_CREATED,
    FINANCE_FIXED_ASSET_DISPOSED,
    FINANCE_FIXED_ASSET_UPDATED,
)
from core.core.constants import (
    ACCUMULATED_DEPRECIATION_ACCOUNT_CODE,
    DEPRECIATION_EXPENSE_ACCOUNT_CODE,
    JOURNAL_SOURCE_DEPRECIATION,
)
from core.domain.entities import (
    DepreciationEntry,
    FixedAsset,
    JournalEntry,
    JournalLine,
)
from core.domain.value_objects import DepreciationMethod, EntryStatus, FixedAssetStatus
from core.features.finance.ports import (
    AuditSink,
    FinanceRepositoryPort,
    FinanceWave4RepositoryPort,
)
from core.features.finance.schemas_wave5 import (
    DepreciationEntryResponse,
    DepreciationRunResponse,
    FixedAssetCreateRequest,
    FixedAssetResponse,
    FixedAssetUpdateRequest,
)
from skyrict_common.exceptions import ConflictError, NotFoundError, ValidationError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/assets", tags=["finance-assets"])

require_asset_read = require_permission("erp.asset.read")
require_asset_write = require_permission("erp.asset.write")
require_asset_run = require_permission("erp.asset.run")

MONTHS_PER_YEAR = Decimal("12")
ROUND = Decimal("0.01")


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _to_period(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _period_parts(period: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in period.split("-", maxsplit=1))
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"Invalid period '{period}' - expected YYYY-MM") from exc
    if not 1 <= month <= 12:
        raise ValidationError(f"Invalid month {month} in period '{period}'")
    return year, month


class FinanceDepreciationService:
    """Capital asset register + straight-line depreciation engine."""

    def __init__(
        self,
        repo: FinanceWave4RepositoryPort,
        ledger: FinanceRepositoryPort,
        audit: AuditSink,
    ) -> None:
        self._repo = repo
        self._ledger = ledger
        self._audit = audit

    # -- Asset CRUD ---------------------------------------------------------

    async def create_asset(self, tenant_id: uuid.UUID, user_id: uuid.UUID, body: Any) -> FixedAsset:
        asset = FixedAsset(
            tenant_id=tenant_id,
            name=str(body.name),
            category=body.category,
            cost=Decimal(body.cost),
            acquisition_date=body.acquisition_date,
            useful_life_years=int(body.useful_life_years),
            depreciation_method=DepreciationMethod(body.depreciation_method),
            salvage_value=Decimal(body.salvage_value or 0),
            created_by=user_id,
        )
        created = await self._repo.create_fixed_asset(asset)
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_FIXED_ASSET_CREATED,
            target=f"fixed_asset:{created.id}",
            details={"name": created.name, "cost": str(created.cost)},
        )
        return created

    async def get_asset(self, tenant_id: uuid.UUID, asset_id: uuid.UUID) -> FixedAsset:
        asset = await self._repo.get_fixed_asset(asset_id, tenant_id)
        if asset is None:
            raise NotFoundError(f"Fixed asset {asset_id} not found")
        return asset

    async def list_assets(self, tenant_id: uuid.UUID, status: str | None) -> list[FixedAsset]:
        return list(await self._repo.list_fixed_assets(tenant_id, status=status))

    async def update_asset(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, asset_id: uuid.UUID, body: Any
    ) -> FixedAsset:
        current = await self.get_asset(tenant_id, asset_id)
        if current.status is not FixedAssetStatus.ACTIVE:
            raise ValidationError("Only active assets can be edited")
        updated = replace(
            current,
            name=body.name if body.name is not None else current.name,
            category=body.category if body.category is not None else current.category,
            cost=Decimal(body.cost) if body.cost is not None else current.cost,
            acquisition_date=(
                body.acquisition_date
                if body.acquisition_date is not None
                else current.acquisition_date
            ),
            useful_life_years=(
                int(body.useful_life_years)
                if body.useful_life_years is not None
                else current.useful_life_years
            ),
            salvage_value=(
                Decimal(body.salvage_value)
                if body.salvage_value is not None
                else current.salvage_value
            ),
        )
        result = await self._repo.update_fixed_asset(updated)
        if result is None:
            raise NotFoundError(f"Fixed asset {asset_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_FIXED_ASSET_UPDATED,
            target=f"fixed_asset:{asset_id}",
            details={"name": result.name, "cost": str(result.cost)},
        )
        return result

    async def dispose(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, asset_id: uuid.UUID, disposed_on: date
    ) -> FixedAsset:
        current = await self.get_asset(tenant_id, asset_id)
        if current.status is FixedAssetStatus.DISPOSED:
            raise ValidationError("Asset is already disposed")
        if disposed_on < current.acquisition_date:
            raise ValidationError("Disposal date cannot precede acquisition date")
        updated = replace(
            current,
            status=FixedAssetStatus.DISPOSED,
            disposed_at=disposed_on,
        )
        result = await self._repo.update_fixed_asset(updated)
        if result is None:
            raise NotFoundError(f"Fixed asset {asset_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_FIXED_ASSET_DISPOSED,
            target=f"fixed_asset:{asset_id}",
            details={"disposed_on": disposed_on.isoformat()},
        )
        return result

    # -- Depreciation engine ------------------------------------------------

    def _period_accrual(self, asset: FixedAsset, period: str) -> Decimal:
        """Straight-line accrual for one period (half-year in acquisition year)."""
        if asset.depreciation_method is not DepreciationMethod.STRAIGHT_LINE:
            raise ValidationError(
                f"Depreciation method '{asset.depreciation_method}' is not supported yet"
            )
        year, _ = _period_parts(period)
        if year < asset.acquisition_date.year:
            return Decimal("0")
        depreciable = asset.cost - asset.salvage_value
        if depreciable <= 0:
            return Decimal("0")
        annual = depreciable / Decimal(asset.useful_life_years)
        if year == asset.acquisition_date.year:
            annual = annual / 2  # half-year convention in the acquisition year
        rounded = (annual / MONTHS_PER_YEAR).quantize(ROUND)
        remaining = depreciable - asset.accumulated_depreciation
        return min(rounded, remaining)

    async def run_period(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, period: str
    ) -> DepreciationRunResponse:
        year, _ = _period_parts(period)
        assets = await self._repo.list_fixed_assets(tenant_id, status=FixedAssetStatus.ACTIVE)
        entry_ids: list[uuid.UUID] = []
        skipped = 0
        total = Decimal("0")
        for asset in assets:
            if asset.id is None:
                continue
            existing = await self._repo.get_depreciation_entry(asset.id, period, tenant_id)
            if existing is not None:
                skipped += 1
                continue
            amount = self._period_accrual(asset, period)
            if amount <= 0:
                skipped += 1
                continue
            entry = await self._book_draft(tenant_id, user_id, asset, period, amount)
            if entry.id is not None:
                entry_ids.append(entry.id)
            if asset.id is not None:
                total += amount
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_DEPRECIATION_RUN,
            target=f"depreciation_run:{year}",
            details={"period": period, "entries": len(entry_ids), "total": str(total)},
        )
        return DepreciationRunResponse(
            period=period,
            ran_at=datetime.now(UTC),
            assets_considered=len(assets),
            entries_created=len(entry_ids),
            entries_skipped=skipped,
            total_amount=total,
            entry_ids=entry_ids,
        )

    async def _book_draft(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        asset: FixedAsset,
        period: str,
        amount: Decimal,
    ) -> DepreciationEntry:
        if asset.id is None:
            raise ValidationError("Asset id was not assigned on create")
        year, month = _period_parts(period)
        entry_date = date(year, month, 28)
        expense_acct = await self._ledger.get_account_by_code(
            DEPRECIATION_EXPENSE_ACCOUNT_CODE, tenant_id
        )
        contra_acct = await self._ledger.get_account_by_code(
            ACCUMULATED_DEPRECIATION_ACCOUNT_CODE, tenant_id
        )
        if (
            expense_acct is None
            or expense_acct.id is None
            or contra_acct is None
            or contra_acct.id is None
        ):
            raise ValidationError(
                f"Depreciation needs account codes "
                f"'{DEPRECIATION_EXPENSE_ACCOUNT_CODE}' (expense) and "
                f"'{ACCUMULATED_DEPRECIATION_ACCOUNT_CODE}' (accumulated depreciation) "
                "in the chart of accounts"
            )
        source_ref = f"{asset.id}:{period}"
        entry = JournalEntry(
            tenant_id=tenant_id,
            entry_date=entry_date,
            memo=f"Depreciation {period} - {asset.name}",
            status=EntryStatus.DRAFT,
            source=JOURNAL_SOURCE_DEPRECIATION,
            source_ref=source_ref,
            lines=(
                JournalLine(
                    account_id=expense_acct.id,
                    debit=amount,
                    credit=None,
                    currency="USD",
                ),
                JournalLine(
                    account_id=contra_acct.id,
                    debit=None,
                    credit=amount,
                    currency="USD",
                ),
            ),
        )
        try:
            journal = await self._ledger.create_journal_entry(entry)
        except ConflictError:
            # Replayed run for a (asset, period) that already booked: treat as
            # skipped idempotently (the unique lock did its job).
            existing = await self._repo.get_depreciation_entry(asset.id, period, tenant_id)
            if existing is not None:
                return existing
            raise
        depreciation = DepreciationEntry(
            tenant_id=tenant_id,
            asset_id=asset.id,
            period=period,
            amount=amount,
            status="draft",
            journal_entry_id=journal.id,
        )
        created = await self._repo.create_depreciation_entry(depreciation)
        updated_accumulated = asset.accumulated_depreciation + amount
        status = (
            FixedAssetStatus.FULLY_DEPRECIATED
            if updated_accumulated >= asset.cost - asset.salvage_value
            else FixedAssetStatus.ACTIVE
        )
        await self._repo.update_fixed_asset(
            replace(asset, accumulated_depreciation=updated_accumulated, status=status)
        )
        return created

    async def list_entries(
        self, tenant_id: uuid.UUID, period: str | None
    ) -> list[DepreciationEntry]:
        return list(await self._repo.list_depreciation_entries(tenant_id, period=period))


@router.post("", response_model=ResponseEnvelope[FixedAssetResponse])
async def create_asset(
    body: FixedAssetCreateRequest,
    current_user: dict[str, Any] = Depends(require_asset_write),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[FixedAssetResponse]:
    asset = await svc.create_asset(_tenant_id(current_user), _user_id(current_user), body)
    return ResponseEnvelope(data=FixedAssetResponse.model_validate(asset))


@router.get("", response_model=ResponseEnvelope[list[FixedAssetResponse]])
async def list_assets(
    status: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(require_asset_read),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[list[FixedAssetResponse]]:
    assets = await svc.list_assets(_tenant_id(current_user), status)
    return ResponseEnvelope(data=[FixedAssetResponse.model_validate(a) for a in assets])


@router.post("/depreciation/run", response_model=ResponseEnvelope[DepreciationRunResponse])
async def run_depreciation(
    period: str = Query(..., description="Period to accrue: YYYY-MM"),
    current_user: dict[str, Any] = Depends(require_asset_run),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[DepreciationRunResponse]:
    result = await svc.run_period(_tenant_id(current_user), _user_id(current_user), period)
    return ResponseEnvelope(data=result)


@router.get(
    "/depreciation/entries", response_model=ResponseEnvelope[list[DepreciationEntryResponse]]
)
async def list_depreciation_entries(
    period: str | None = Query(default=None),
    current_user: dict[str, Any] = Depends(require_asset_read),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[list[DepreciationEntryResponse]]:
    entries = await svc.list_entries(_tenant_id(current_user), period)
    return ResponseEnvelope(data=[DepreciationEntryResponse.model_validate(e) for e in entries])


@router.get("/{asset_id}", response_model=ResponseEnvelope[FixedAssetResponse])
async def get_asset(
    asset_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_asset_read),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[FixedAssetResponse]:
    asset = await svc.get_asset(_tenant_id(current_user), asset_id)
    return ResponseEnvelope(data=FixedAssetResponse.model_validate(asset))


@router.put("/{asset_id}", response_model=ResponseEnvelope[FixedAssetResponse])
async def update_asset(
    asset_id: uuid.UUID,
    body: FixedAssetUpdateRequest,
    current_user: dict[str, Any] = Depends(require_asset_write),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[FixedAssetResponse]:
    asset = await svc.update_asset(_tenant_id(current_user), _user_id(current_user), asset_id, body)
    return ResponseEnvelope(data=FixedAssetResponse.model_validate(asset))


@router.post("/{asset_id}/dispose", response_model=ResponseEnvelope[FixedAssetResponse])
async def dispose_asset(
    asset_id: uuid.UUID,
    disposed_on: date = Query(..., description="Disposal date"),
    current_user: dict[str, Any] = Depends(require_asset_write),
    svc: FinanceDepreciationService = Depends(get_finance_depreciation_service),
) -> ResponseEnvelope[FixedAssetResponse]:
    asset = await svc.dispose(
        _tenant_id(current_user), _user_id(current_user), asset_id, disposed_on
    )
    return ResponseEnvelope(data=FixedAssetResponse.model_validate(asset))
