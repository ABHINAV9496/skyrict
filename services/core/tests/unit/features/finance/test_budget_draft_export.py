"""FinanceService unit tests - workforce budget-draft export (HR-AI-004, SKY-93).

Uses an in-memory repository double; the UNIQUE-idempotency replay path is
exercised by raising ConflictError on a duplicate, mirroring the repository.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from core.core.constants import BUDGET_DRAFT_SOURCE_WORKFORCE_PLAN
from core.core.exceptions import ConflictError
from core.domain.entities import BudgetDraft
from core.features.finance.service import FinanceService

TENANT = uuid.uuid4()
SCENARIO = uuid.uuid4()
ACTOR = uuid.uuid4()


class _Session:
    async def rollback(self) -> None:
        pass


class _FakeRepo:
    def __init__(self) -> None:
        self.saved: list[BudgetDraft] = []

    @property
    def session(self) -> _Session:
        return _Session()

    async def create_budget_draft(self, draft: BudgetDraft) -> BudgetDraft:
        if any(
            d.source == draft.source and d.source_ref == draft.source_ref
            for d in self.saved
        ):
            raise ConflictError("Budget draft already exists for this scenario")
        created = BudgetDraft(
            tenant_id=draft.tenant_id,
            scenario_id=draft.scenario_id,
            scenario_name=draft.scenario_name,
            status=draft.status,
            source=draft.source,
            source_ref=draft.source_ref,
            currency=draft.currency,
            horizon=draft.horizon,
            base_as_of=draft.base_as_of,
            salary_total=draft.salary_total,
            benefit_total=draft.benefit_total,
            grand_total=draft.grand_total,
            created_by=draft.created_by,
            lines=draft.lines,
            id=uuid.uuid4(),
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
            updated_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
        self.saved.append(created)
        return created

    async def get_workforce_budget_draft_id(
        self,
        *,
        tenant_id: uuid.UUID,
        source_ref: str,
    ) -> uuid.UUID | None:
        for d in self.saved:
            if d.source_ref == source_ref:
                return d.id
        return None


class _NoopAudit:
    async def log(self, **kwargs: Any) -> None:
        pass


class _NoopEvents:
    pass


def _service(repo: _FakeRepo) -> FinanceService:
    return FinanceService(repo=repo, audit=_NoopAudit(), events=_NoopEvents())


async def _export(service: FinanceService) -> object:
    return await service.create_workforce_budget_draft(
        tenant_id=TENANT,
        scenario_id=SCENARIO,
        scenario_name="five-percent",
        base_as_of=date(2026, 1, 1),
        horizon=12,
        currency="USD",
        salary_total=Decimal("52500.00"),
        benefit_total=Decimal("5250.00"),
        grand_total=Decimal("57750.00"),
        created_by=ACTOR,
    )


async def test_export_creates_draft_status_source_and_lines() -> None:
    repo = _FakeRepo()
    service = _service(repo)

    outcome = await _export(service)

    assert outcome.already_booked is False
    assert outcome.draft_id is not None

    saved = repo.saved[0]
    assert saved.status == "draft"
    assert saved.source == BUDGET_DRAFT_SOURCE_WORKFORCE_PLAN
    assert saved.source_ref == str(SCENARIO)
    assert saved.scenario_id == SCENARIO
    assert saved.scenario_name == "five-percent"
    assert saved.base_as_of == date(2026, 1, 1)
    assert saved.horizon == 12
    assert saved.currency == "USD"
    assert saved.salary_total == Decimal("52500.00")
    assert saved.benefit_total == Decimal("5250.00")
    assert saved.grand_total == Decimal("57750.00")
    assert len(saved.lines) == 2
    assert (saved.lines[0].line_no, saved.lines[0].label, saved.lines[0].amount) == (
        1,
        "Salary",
        Decimal("52500.00"),
    )
    assert (saved.lines[1].line_no, saved.lines[1].label, saved.lines[1].amount) == (
        2,
        "Benefits",
        Decimal("5250.00"),
    )


async def test_replayed_export_reports_already_booked_single_draft() -> None:
    repo = _FakeRepo()
    service = _service(repo)

    first = await _export(service)
    second = await _export(service)

    assert first.already_booked is False
    assert first.draft_id is not None
    assert second.already_booked is True
    assert second.draft_id == first.draft_id  # replay returns the existing draft
    assert len(repo.saved) == 1  # idempotency lock -> no second draft
