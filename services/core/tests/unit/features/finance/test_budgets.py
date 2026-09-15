"""Unit tests for operating budgets (FIN-AUT-004, SKY-85 B21).

Covers budget lifecycle (draft → active → closed), line mutations, and
variance computation. Repository persistence is tested by integration suites.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from core.core.audit_events import (
    FINANCE_BUDGET_ACTIVATED,
    FINANCE_BUDGET_CLOSED,
    FINANCE_BUDGET_CREATED,
    FINANCE_BUDGET_UPDATED,
)
from core.domain.value_objects import BudgetStatus
from core.features.finance.budgets import FinanceBudgetsService
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from core.domain.entities import Budget, BudgetLine


class StubBudgetRepo:
    def __init__(self) -> None:
        self.budgets: dict[uuid.UUID, Budget] = {}
        self.lines: dict[uuid.UUID, BudgetLine] = {}
        self.actuals: dict[str, Decimal] = {}

    async def create_budget(self, budget: Budget) -> Budget:
        bid = uuid.uuid4()
        stored = replace(budget, id=bid)
        self.budgets[bid] = stored
        return stored

    async def get_budget(self, budget_id: uuid.UUID, tenant_id: uuid.UUID) -> Budget | None:
        b = self.budgets.get(budget_id)
        return b if b is not None and b.tenant_id == tenant_id else None

    async def list_budgets(
        self, tenant_id: uuid.UUID, *, status: str | None = None
    ) -> list[Budget]:
        values = [b for b in self.budgets.values() if b.tenant_id == tenant_id]
        if status is not None:
            values = [b for b in values if b.status == status]
        return values

    async def update_budget(self, budget: Budget) -> Budget | None:
        if budget.id is None or budget.id not in self.budgets:
            return None
        self.budgets[budget.id] = budget
        return budget

    async def delete_budgetlines(self, tenant_id: uuid.UUID, budget_id: uuid.UUID) -> None:
        self.lines = {k: v for k, v in self.lines.items() if v.budget_id != budget_id}

    async def add_budgetline(self, line: BudgetLine) -> BudgetLine:
        lid = uuid.uuid4()
        stored = replace(line, id=lid)
        self.lines[lid] = stored
        return stored

    async def add_budgetlines(self, lines: list[BudgetLine]) -> list[BudgetLine]:
        return [await self.add_budgetline(line) for line in lines]

    async def list_budget_lines(
        self, tenant_id: uuid.UUID, budget_id: uuid.UUID
    ) -> list[BudgetLine]:
        return [line for line in self.lines.values() if line.budget_id == budget_id]

    async def posted_totals_by_code(
        self, tenant_id: uuid.UUID, fiscal_year_start: Any, fiscal_year_end: Any
    ) -> dict[str, Decimal]:
        return dict(self.actuals)


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _body(name: str = "FY2026 Ops", **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "name": name,
        "fiscal_year": 2026,
        "description": None,
        "currency": "USD",
        "lines": [
            SimpleNamespace(account_code="6010", amount=Decimal("100000")),
            SimpleNamespace(account_code="5010", amount=Decimal("50000")),
        ],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _fresh() -> tuple[StubBudgetRepo, RecordingAudit, FinanceBudgetsService]:
    repo = StubBudgetRepo()
    audit = RecordingAudit()
    return repo, audit, FinanceBudgetsService(repo=repo, audit=audit)


async def test_create_budget_with_lines() -> None:
    repo, audit, svc = _fresh()
    budget = await svc.create_budget(TENANT, USER, _body())
    assert budget.id is not None
    assert budget.status == BudgetStatus.DRAFT
    assert audit.logs[-1]["action"] == FINANCE_BUDGET_CREATED
    lines = await repo.list_budget_lines(TENANT, budget.id)
    assert len(lines) == 2


async def test_create_budget_missing_id_raises() -> None:
    """Budget.id must be set by the repo; the service guards against None."""

    class BadRepo(StubBudgetRepo):
        async def create_budget(self, budget: Budget) -> Budget:
            return replace(budget, id=None)

    svc = FinanceBudgetsService(repo=BadRepo(), audit=RecordingAudit())
    with pytest.raises(ValidationError, match="not assigned"):
        await svc.create_budget(TENANT, USER, _body())


async def test_get_budget_not_found() -> None:
    _, _, svc = _fresh()
    with pytest.raises(NotFoundError):
        await svc.get_budget(TENANT, uuid.uuid4())


async def test_list_budgets_status_filter() -> None:
    _repo, _, svc = _fresh()
    await svc.create_budget(TENANT, USER, _body("A"))
    b2 = await svc.create_budget(TENANT, USER, _body("B"))
    await svc.activate(TENANT, USER, b2.id)
    assert len(await svc.list_budgets(TENANT, None)) == 2
    assert len(await svc.list_budgets(TENANT, "draft")) == 1
    assert len(await svc.list_budgets(TENANT, "active")) == 1


async def test_update_budget_on_draft() -> None:
    _repo, audit, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    updated = await svc.update_budget(
        TENANT, USER, created.id, SimpleNamespace(name="New", description="d", currency=None)
    )
    assert updated.name == "New"
    assert updated.description == "d"
    assert updated.currency == "USD"
    assert audit.logs[-1]["action"] == FINANCE_BUDGET_UPDATED


async def test_update_budget_rejects_non_draft() -> None:
    _repo, _, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    await svc.activate(TENANT, USER, created.id)
    with pytest.raises(ValidationError, match="Only draft"):
        await svc.update_budget(TENANT, USER, created.id, _body("X"))


async def test_activate_from_draft() -> None:
    _repo, audit, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    activated = await svc.activate(TENANT, USER, created.id)
    assert activated.status == BudgetStatus.ACTIVE
    assert audit.logs[-1]["action"] == FINANCE_BUDGET_ACTIVATED


async def test_activate_rejects_closed() -> None:
    _repo, _, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    await svc.activate(TENANT, USER, created.id)
    await svc.close(TENANT, USER, created.id)
    with pytest.raises(ValidationError, match="closed"):
        await svc.activate(TENANT, USER, created.id)


async def test_close_from_active() -> None:
    _repo, audit, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    await svc.activate(TENANT, USER, created.id)
    closed = await svc.close(TENANT, USER, created.id)
    assert closed.status == BudgetStatus.CLOSED
    assert audit.logs[-1]["action"] == FINANCE_BUDGET_CLOSED


async def test_close_rejects_non_active() -> None:
    _, _, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    with pytest.raises(ValidationError, match="Only an active"):
        await svc.close(TENANT, USER, created.id)


async def test_add_lines_on_draft() -> None:
    _repo, _, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body("empty", lines=[]))
    lines = await svc.add_lines(
        TENANT, USER, created.id, [SimpleNamespace(account_code="4000", amount=Decimal("75000"))]
    )
    assert len(lines) == 1
    assert lines[0].account_code == "4000"


async def test_add_lines_rejects_non_draft() -> None:
    _, _, svc = _fresh()
    created = await svc.create_budget(TENANT, USER, _body())
    await svc.activate(TENANT, USER, created.id)
    with pytest.raises(ValidationError, match="Only draft"):
        await svc.add_lines(TENANT, USER, created.id, [])


async def test_variance_flags_amber_at_10pct() -> None:
    repo, _, svc = _fresh()
    budget = await svc.create_budget(
        TENANT,
        USER,
        _body("Var", lines=[SimpleNamespace(account_code="6010", amount=Decimal("1000"))]),
    )
    await svc.activate(TENANT, USER, budget.id)
    # actual = 1200, planned = 1000, variance = +20% → amber
    repo.actuals = {"6010": Decimal("1200")}
    result = await svc.variance(TENANT, budget.id)
    assert result.flagged_count == 1
    assert result.lines[0].flag == "amber"
    assert result.lines[0].variance_pct == Decimal("0.20")


async def test_variance_ok_within_threshold() -> None:
    repo, _, svc = _fresh()
    budget = await svc.create_budget(
        TENANT,
        USER,
        _body("Var", lines=[SimpleNamespace(account_code="6010", amount=Decimal("1000"))]),
    )
    await svc.activate(TENANT, USER, budget.id)
    repo.actuals = {"6010": Decimal("1050")}
    result = await svc.variance(TENANT, budget.id)
    assert result.flagged_count == 0
    assert result.lines[0].flag == "ok"


async def test_variance_rejects_non_active() -> None:
    _, _, svc = _fresh()
    budget = await svc.create_budget(TENANT, USER, _body())
    with pytest.raises(ValidationError, match="only available for an active"):
        await svc.variance(TENANT, budget.id)
