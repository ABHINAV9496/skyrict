"""Unit tests for compliance calendar (FIN-AUT-004, SKY-85 B27).

Covers compliance item CRUD, recurrence advancement on complete, overdue
derivation, and upcoming reminders. Repository persistence tested by
integration suites.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from core.core.audit_events import (
    FINANCE_COMPLIANCE_ITEM_COMPLETED,
    FINANCE_COMPLIANCE_ITEM_CREATED,
    FINANCE_COMPLIANCE_ITEM_UPDATED,
)
from core.domain.value_objects import ComplianceItemStatus
from core.features.finance.compliance_calendar import FinanceComplianceService
from skyrict_common.exceptions import NotFoundError, ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.domain.entities import ComplianceItem


class StubComplianceRepo:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, ComplianceItem] = {}

    async def create_compliance_item(self, item: ComplianceItem) -> ComplianceItem:
        iid = uuid.uuid4()
        stored = replace(item, id=iid)
        self.items[iid] = stored
        return stored

    async def get_compliance_item(
        self, item_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> ComplianceItem | None:
        i = self.items.get(item_id)
        return i if i is not None and i.tenant_id == tenant_id else None

    async def list_compliance_items(
        self, tenant_id: uuid.UUID, *, status: str | None = None
    ) -> Sequence[ComplianceItem]:
        values = [i for i in self.items.values() if i.tenant_id == tenant_id]
        if status is not None:
            values = [i for i in values if i.status == status]
        return values

    async def list_compliance_due(
        self, tenant_id: uuid.UUID, due_on_or_before: date
    ) -> Sequence[ComplianceItem]:
        return [
            i
            for i in self.items.values()
            if i.tenant_id == tenant_id
            and i.status == ComplianceItemStatus.OPEN
            and i.due_on <= due_on_or_before
        ]

    async def complete_compliance_item(
        self, item_id: uuid.UUID, tenant_id: uuid.UUID, *, completed_by, completed_at
    ) -> ComplianceItem | None:
        i = self.items.get(item_id)
        if i is None or i.tenant_id != tenant_id:
            return None
        updated = replace(
            i,
            status=ComplianceItemStatus.COMPLETED,
            completed_by=completed_by,
            completed_at=completed_at,
        )
        self.items[item_id] = updated
        return updated

    async def update_compliance_item(self, item: ComplianceItem) -> ComplianceItem | None:
        if item.id is None or item.id not in self.items:
            return None
        self.items[item.id] = item
        return item


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


TENANT = uuid.uuid4()
USER = uuid.uuid4()


def _fresh() -> tuple[StubComplianceRepo, RecordingAudit, FinanceComplianceService]:
    repo = StubComplianceRepo()
    audit = RecordingAudit()
    return repo, audit, FinanceComplianceService(repo=repo, audit=audit)


def _body(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "title": "VAT Return",
        "due_on": date(2026, 3, 31),
        "description": "Quarterly VAT filing",
        "obligation_type": "tax",
        "recurrence": None,
        "lead_days": 14,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


async def test_create_item() -> None:
    _, audit, svc = _fresh()
    item = await svc.create_item(TENANT, USER, _body())
    assert item.id is not None
    assert item.title == "VAT Return"
    assert item.status == ComplianceItemStatus.OPEN
    assert audit.logs[-1]["action"] == FINANCE_COMPLIANCE_ITEM_CREATED


async def test_get_item_not_found() -> None:
    _, _, svc = _fresh()
    with pytest.raises(NotFoundError):
        await svc.get_item(TENANT, uuid.uuid4())


async def test_list_items_status_filter() -> None:
    _repo, _, svc = _fresh()
    i1 = await svc.create_item(TENANT, USER, _body(title="A"))
    _i2 = await svc.create_item(TENANT, USER, _body(title="B", recurrence="monthly"))
    await svc.complete(TENANT, USER, i1.id)
    assert len(await svc.list_items(TENANT, None)) == 2
    assert len(await svc.list_items(TENANT, "completed")) == 1
    assert len(await svc.list_items(TENANT, "open")) == 1


async def test_update_item() -> None:
    _repo, audit, svc = _fresh()
    item = await svc.create_item(TENANT, USER, _body())
    updated = await svc.update_item(
        TENANT,
        USER,
        item.id,
        SimpleNamespace(
            title="Updated",
            due_on=None,
            description=None,
            obligation_type=None,
            recurrence=None,
            lead_days=None,
        ),
    )
    assert updated.title == "Updated"
    assert audit.logs[-1]["action"] == FINANCE_COMPLIANCE_ITEM_UPDATED


async def test_update_rejects_non_open() -> None:
    _repo, _, svc = _fresh()
    item = await svc.create_item(TENANT, USER, _body())
    await svc.complete(TENANT, USER, item.id)
    with pytest.raises(ValidationError, match="Only open"):
        await svc.update_item(TENANT, USER, item.id, _body(title="X"))


async def test_complete_oneoff() -> None:
    _repo, audit, svc = _fresh()
    item = await svc.create_item(TENANT, USER, _body())
    completed = await svc.complete(TENANT, USER, item.id)
    assert completed.status == ComplianceItemStatus.COMPLETED
    assert completed.completed_by == USER
    assert completed.completed_at is not None
    assert audit.logs[-1]["action"] == FINANCE_COMPLIANCE_ITEM_COMPLETED


async def test_complete_recurring_advances_due_on() -> None:
    repo, _, svc = _fresh()
    item = await svc.create_item(
        TENANT, USER, _body(due_on=date(2026, 6, 30), recurrence="quarterly")
    )
    completed = await svc.complete(TENANT, USER, item.id)
    # Recurring items reopen with advanced due_on
    assert completed.status == ComplianceItemStatus.OPEN
    assert completed.due_on > item.due_on
    # Original is removed; new item is created via update
    assert repo.items[completed.id].due_on == completed.due_on


async def test_complete_monthly_advances_one_month() -> None:
    _repo, _, svc = _fresh()
    today = date.today()
    item = await svc.create_item(
        TENANT, USER, _body(due_on=today - timedelta(days=60), recurrence="monthly")
    )
    completed = await svc.complete(TENANT, USER, item.id)
    assert completed.status == ComplianceItemStatus.OPEN
    assert completed.due_on > today
    assert completed.id == item.id  # advanced in place
    assert completed.due_on <= today + timedelta(days=40)  # not skipped far ahead


async def test_complete_yearly_advances_one_year() -> None:
    _repo, _, svc = _fresh()
    item = await svc.create_item(TENANT, USER, _body(due_on=date(2026, 2, 28), recurrence="yearly"))
    completed = await svc.complete(TENANT, USER, item.id)
    assert completed.due_on == date(2027, 2, 28)


async def test_list_upcoming_uses_lead_days() -> None:
    _repo, _, svc = _fresh()
    today = date.today()
    await svc.create_item(TENANT, USER, _body(due_on=today + timedelta(days=5), title="soon"))
    await svc.create_item(TENANT, USER, _body(due_on=today + timedelta(days=60), title="later"))
    upcoming = await svc.list_upcoming(TENANT, 14)
    titles = {i.title for i in upcoming}
    assert "soon" in titles
    assert "later" not in titles


async def test_invalid_recurrence_raises() -> None:
    _, _, svc = _fresh()
    with pytest.raises(ValidationError, match="Invalid recurrence"):
        await svc.create_item(TENANT, USER, _body(recurrence="weekly"))
