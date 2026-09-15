"""Finance budgets (FIN-AUT-004, SKY-85 B21).

Thin service + router for fiscal-year operating budgets. A budget moves
``draft -> active -> closed``; only ``draft`` editable, ``active`` is the
variance-read target. Lines reference ``account_code`` strings (journal
template style) so the plan survives account renames; the variance read-side
resolves each line's code via the ledger's POSTED activity for the budget's
fiscal year and flags accounts at or beyond +/-10% variance (amber).

Reads use ``erp.budget.read``; every write uses ``erp.budget.write``.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends

from core.api.deps import (
    get_finance_budgets_service,
    require_permission,
)
from core.core.audit_events import (
    FINANCE_BUDGET_ACTIVATED,
    FINANCE_BUDGET_CLOSED,
    FINANCE_BUDGET_CREATED,
    FINANCE_BUDGET_UPDATED,
)
from core.domain.entities import Budget, BudgetLine
from core.domain.value_objects import BudgetStatus
from core.features.finance.ports import AuditSink, FinanceWave4RepositoryPort
from core.features.finance.schemas_wave5 import (
    BudgetCreateRequest,
    BudgetLineRequest,
    BudgetResponse,
    BudgetUpdateRequest,
    BudgetVarianceLineResponse,
    BudgetVarianceResponse,
)
from skyrict_common.exceptions import NotFoundError, ValidationError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/finance/budgets", tags=["finance-budgets"])

require_budget_read = require_permission("erp.budget.read")
require_budget_write = require_permission("erp.budget.write")

VARIANCE_FLAG_PCT = Decimal("0.10")


def _tenant_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["tenant_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


def _user_id(current_user: dict[str, Any]) -> uuid.UUID:
    val = current_user["user_id"]
    return val if isinstance(val, uuid.UUID) else uuid.UUID(val)


class FinanceBudgetsService:
    """Business rules for operating budgets (thin over the repo)."""

    def __init__(self, repo: FinanceWave4RepositoryPort, audit: AuditSink) -> None:
        self._repo = repo
        self._audit = audit

    async def create_budget(self, tenant_id: uuid.UUID, user_id: uuid.UUID, body: Any) -> Budget:
        created = await self._repo.create_budget(
            Budget(
                tenant_id=tenant_id,
                name=str(body.name),
                fiscal_year=int(body.fiscal_year),
                description=body.description,
                currency=str(body.currency or "USD"),
                created_by=user_id,
            )
        )
        if created.id is None:
            raise ValidationError("Budget id was not assigned on create")
        lines = await self.add_lines(tenant_id, user_id, created.id, body.lines)
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_BUDGET_CREATED,
            target=f"budget:{created.id}",
            details={"name": created.name, "fiscal_year": created.fiscal_year, "lines": len(lines)},
        )
        return created

    async def get_budget(self, tenant_id: uuid.UUID, budget_id: uuid.UUID) -> Budget:
        budget = await self._repo.get_budget(budget_id, tenant_id)
        if budget is None:
            raise NotFoundError(f"Budget {budget_id} not found")
        return budget

    async def list_budgets(self, tenant_id: uuid.UUID, status: str | None) -> list[Budget]:
        return list(await self._repo.list_budgets(tenant_id, status=status))

    async def update_budget(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, budget_id: uuid.UUID, body: Any
    ) -> Budget:
        current = await self.get_budget(tenant_id, budget_id)
        if current.status is not BudgetStatus.DRAFT:
            raise ValidationError("Only draft budgets can be edited - activate freezes the plan")
        updated = replace(
            current,
            name=body.name if body.name is not None else current.name,
            description=body.description if body.description is not None else current.description,
            currency=body.currency if body.currency is not None else current.currency,
        )
        result = await self._repo.update_budget(updated)
        if result is None:
            raise NotFoundError(f"Budget {budget_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_BUDGET_UPDATED,
            target=f"budget:{budget_id}",
            details={"name": result.name},
        )
        return result

    async def activate(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, budget_id: uuid.UUID
    ) -> Budget:
        current = await self.get_budget(tenant_id, budget_id)
        if current.status is BudgetStatus.CLOSED:
            raise ValidationError("A closed budget cannot be activated")
        if current.status is not BudgetStatus.DRAFT:
            raise ValidationError(f"Budget is already {current.status}")
        updated = replace(current, status=BudgetStatus.ACTIVE)
        result = await self._repo.update_budget(updated)
        if result is None:
            raise NotFoundError(f"Budget {budget_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_BUDGET_ACTIVATED,
            target=f"budget:{budget_id}",
            details={"fiscal_year": result.fiscal_year},
        )
        return result

    async def close(self, tenant_id: uuid.UUID, user_id: uuid.UUID, budget_id: uuid.UUID) -> Budget:
        current = await self.get_budget(tenant_id, budget_id)
        if current.status is not BudgetStatus.ACTIVE:
            raise ValidationError("Only an active budget can be closed")
        updated = replace(current, status=BudgetStatus.CLOSED)
        result = await self._repo.update_budget(updated)
        if result is None:
            raise NotFoundError(f"Budget {budget_id} not found")
        await self._audit.log(
            tenant_id=tenant_id,
            user_id=user_id,
            action=FINANCE_BUDGET_CLOSED,
            target=f"budget:{budget_id}",
        )
        return result

    async def add_lines(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        budget_id: uuid.UUID,
        raw_lines: list[Any],
    ) -> list[BudgetLine]:
        budget = await self.get_budget(tenant_id, budget_id)
        if budget.status is not BudgetStatus.DRAFT:
            raise ValidationError("Only draft budgets accept line changes")
        lines = [
            BudgetLine(
                tenant_id=tenant_id,
                budget_id=budget_id,
                account_code=str(raw.account_code),
                amount=raw.amount,
            )
            for raw in raw_lines
        ]
        return list(await self._repo.add_budgetlines(lines))

    async def variance(self, tenant_id: uuid.UUID, budget_id: uuid.UUID) -> BudgetVarianceResponse:
        budget = await self.get_budget(tenant_id, budget_id)
        if budget.status is not BudgetStatus.ACTIVE:
            raise ValidationError("Variance is only available for an active budget")
        lines = await self._repo.list_budget_lines(tenant_id, budget_id)
        actuals = await self._repo.posted_totals_by_code(
            tenant_id,
            date(budget.fiscal_year, 1, 1),
            date(budget.fiscal_year, 12, 31),
        )
        variance_lines: list[BudgetVarianceLineResponse] = []
        planned_total = Decimal("0")
        actual_total = Decimal("0")
        flagged = 0
        for line in lines:
            planned = line.amount
            actual = actuals.get(line.account_code, Decimal("0"))
            variance = actual - planned
            pct = (variance / planned) if planned else Decimal("0")
            flag = "amber" if abs(pct) >= VARIANCE_FLAG_PCT else "ok"
            if flag == "amber":
                flagged += 1
            planned_total += planned
            actual_total += actual
            variance_lines.append(
                BudgetVarianceLineResponse(
                    account_code=line.account_code,
                    planned=planned,
                    actual=actual,
                    variance=variance,
                    variance_pct=pct,
                    flag=flag,
                )
            )
        return BudgetVarianceResponse(
            budget_id=budget_id,
            name=budget.name,
            fiscal_year=budget.fiscal_year,
            status=budget.status,
            currency=budget.currency,
            planned_total=planned_total,
            actual_total=actual_total,
            variance_total=actual_total - planned_total,
            flagged_count=flagged,
            lines=variance_lines,
        )


@router.post("", response_model=ResponseEnvelope[BudgetResponse])
async def create_budget(
    body: BudgetCreateRequest,
    current_user: dict[str, Any] = Depends(require_budget_write),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[BudgetResponse]:
    budget = await svc.create_budget(_tenant_id(current_user), _user_id(current_user), body)
    return ResponseEnvelope(data=BudgetResponse.model_validate(budget))


@router.get("", response_model=ResponseEnvelope[list[BudgetResponse]])
async def list_budgets(
    status: str | None = None,
    current_user: dict[str, Any] = Depends(require_budget_read),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[list[BudgetResponse]]:
    budgets = await svc.list_budgets(_tenant_id(current_user), status)
    return ResponseEnvelope(data=[BudgetResponse.model_validate(b) for b in budgets])


@router.get("/{budget_id}", response_model=ResponseEnvelope[BudgetResponse])
async def get_budget(
    budget_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_budget_read),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[BudgetResponse]:
    budget = await svc.get_budget(_tenant_id(current_user), budget_id)
    return ResponseEnvelope(data=BudgetResponse.model_validate(budget))


@router.put("/{budget_id}", response_model=ResponseEnvelope[BudgetResponse])
async def update_budget(
    budget_id: uuid.UUID,
    body: BudgetUpdateRequest,
    current_user: dict[str, Any] = Depends(require_budget_write),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[BudgetResponse]:
    budget = await svc.update_budget(
        _tenant_id(current_user), _user_id(current_user), budget_id, body
    )
    return ResponseEnvelope(data=BudgetResponse.model_validate(budget))


@router.post("/{budget_id}/activate", response_model=ResponseEnvelope[BudgetResponse])
async def activate_budget(
    budget_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_budget_write),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[BudgetResponse]:
    budget = await svc.activate(_tenant_id(current_user), _user_id(current_user), budget_id)
    return ResponseEnvelope(data=BudgetResponse.model_validate(budget))


@router.post("/{budget_id}/close", response_model=ResponseEnvelope[BudgetResponse])
async def close_budget(
    budget_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_budget_write),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[BudgetResponse]:
    budget = await svc.close(_tenant_id(current_user), _user_id(current_user), budget_id)
    return ResponseEnvelope(data=BudgetResponse.model_validate(budget))


@router.post("/{budget_id}/lines", response_model=ResponseEnvelope[list[dict[str, Any]]])
async def add_budget_lines(
    budget_id: uuid.UUID,
    body: list[BudgetLineRequest],
    current_user: dict[str, Any] = Depends(require_budget_write),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[list[dict[str, Any]]]:
    lines = await svc.add_lines(_tenant_id(current_user), _user_id(current_user), budget_id, body)
    return ResponseEnvelope(
        data=[
            {"id": line.id, "account_code": line.account_code, "amount": line.amount}
            for line in lines
        ]
    )


@router.get("/{budget_id}/variance", response_model=ResponseEnvelope[BudgetVarianceResponse])
async def budget_variance(
    budget_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(require_budget_read),
    svc: FinanceBudgetsService = Depends(get_finance_budgets_service),
) -> ResponseEnvelope[BudgetVarianceResponse]:
    result = await svc.variance(_tenant_id(current_user), budget_id)
    return ResponseEnvelope(data=result)
