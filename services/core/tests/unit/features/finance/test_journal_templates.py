"""Unit tests for recurring journal templates (FIN-AUT-003 B5).

Covers the wave-3 service's own decision logic: template CRUD validation
(balanced lines, cron next-run), the exactly-once generate contract (the
``UNIQUE (tenant_id, source, source_ref)`` lock surfaces as a ConflictError the
service turns into ``created=False``), memo ``{date}`` rendering, offset
application, unknown-account failure, and run-due best-effort triage.
Repository persistence is exercised by the migration round-trip / integration
suite, not here.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from core.core.audit_events import (
    FINANCE_JOURNAL_TEMPLATE_CREATED,
    FINANCE_JOURNAL_TEMPLATE_DELETED,
    FINANCE_JOURNAL_TEMPLATE_GENERATED,
    FINANCE_JOURNAL_TEMPLATE_UPDATED,
)
from core.core.constants import JOURNAL_SOURCE_TEMPLATE
from core.domain.value_objects import EntryStatus
from core.features.finance.automation_wave3 import FinanceWave3Service
from skyrict_common.exceptions import ConflictError, NotFoundError, ValidationError

if TYPE_CHECKING:
    from core.domain.entities import JournalTemplate


class StubTemplateRepo:
    """Implements both protocol slices: template storage + entry/account access."""

    def __init__(self) -> None:
        self.templates: dict[uuid.UUID, JournalTemplate] = {}
        self.due_templates: list[JournalTemplate] = []
        self.account_by_code: dict[str, object] = {}
        self.created_entries: list[object] = []
        self.duplicate_source_refs: set[str] = set()
        self.writes: list[tuple[str, object]] = []

    async def create_journal_template(self, template: JournalTemplate) -> JournalTemplate:
        new_id = template.id or uuid.uuid4()
        stored = replace(template, id=new_id)
        self.templates[new_id] = stored
        self.writes.append(("create", stored))
        return stored

    async def get_journal_template(self, template_id, tenant_id):
        return self.templates.get(template_id)

    async def list_journal_templates(self, tenant_id, *, enabled=None):
        values = list(self.templates.values())
        if enabled is None:
            return values
        return [t for t in values if t.enabled is enabled]

    async def update_journal_template(self, template: JournalTemplate):
        self.templates[template.id] = template
        self.writes.append(("update", template))
        return template

    async def delete_journal_template(self, template_id, tenant_id):
        if template_id in self.templates:
            del self.templates[template_id]
            self.writes.append(("delete", template_id))
            return True
        return False

    async def list_journal_templates_due(self, tenant_id, at):
        return self.due_templates

    # --- FinanceRepositoryPort slice used by generate ---

    async def get_account_by_code(self, code, tenant_id):
        return self.account_by_code.get(code)

    async def create_journal_entry(self, entry):
        if entry.source_ref in self.duplicate_source_refs:
            raise ConflictError("already exists")
        self.created_entries.append(entry)
        self.duplicate_source_refs.add(entry.source_ref)
        return SimpleNamespace(id=uuid.uuid4())


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


def _body(name="Monthly rent", **overrides):
    fields = {
        "name": name,
        "cron_expression": "0 0 1 * *",
        "entry_date_offset_days": 0,
        "description": None,
        "memo": "Rent for {date}",
        "lines": [
            SimpleNamespace(account_code="6010", debit=Decimal("1000"), credit=None),
            SimpleNamespace(account_code="1200", debit=None, credit=Decimal("1000")),
        ],
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _fresh_service():
    repo = StubTemplateRepo()
    repo.account_by_code["6010"] = SimpleNamespace(id=uuid.uuid4())
    repo.account_by_code["1200"] = SimpleNamespace(id=uuid.uuid4())
    audit = RecordingAudit()
    service = FinanceWave3Service(repo=repo, entries=repo, audit=audit)
    return repo, audit, service


async def test_create_template_balances_and_schedules() -> None:
    _repo, audit, service = _fresh_service()
    template = await service.create_template(uuid.uuid4(), uuid.uuid4(), _body())
    assert template.enabled is True
    assert template.next_run_at is not None
    assert template.next_run_at > datetime.now(UTC)
    assert template.lines[0].account_code == "6010"
    assert audit.logs[-1]["action"] == FINANCE_JOURNAL_TEMPLATE_CREATED


async def test_create_template_rejects_unbalanced_lines() -> None:
    _, _, service = _fresh_service()
    bad = _body(
        lines=[
            SimpleNamespace(account_code="6010", debit=Decimal("1000"), credit=None),
            SimpleNamespace(account_code="1200", debit=None, credit=Decimal("999")),
        ]
    )
    with pytest.raises(ValidationError, match="balance"):
        await service.create_template(uuid.uuid4(), uuid.uuid4(), bad)


async def test_create_template_rejects_line_with_both_amounts() -> None:
    _, _, service = _fresh_service()
    bad = _body(
        lines=[
            SimpleNamespace(account_code="6010", debit=Decimal("10"), credit=Decimal("10")),
            SimpleNamespace(account_code="1200", debit=None, credit=Decimal("20")),
        ]
    )
    with pytest.raises(ValidationError, match="exactly one"):
        await service.create_template(uuid.uuid4(), uuid.uuid4(), bad)


async def test_update_template_merges_and_recomputes_next_run() -> None:
    _repo, audit, service = _fresh_service()
    created = await service.create_template(uuid.uuid4(), uuid.uuid4(), _body())
    updated = await service.update_template(
        uuid.uuid4(),
        uuid.uuid4(),
        created.id,
        SimpleNamespace(
            name="New name",
            cron_expression=None,
            entry_date_offset_days=1,
            description="desc",
            memo=None,
            enabled=False,
            lines=None,
        ),
    )
    assert updated.name == "New name"
    assert updated.entry_date_offset_days == 1
    assert updated.enabled is False
    assert updated.memo == "Rent for {date}"  # unchanged
    assert audit.logs[-1]["action"] == FINANCE_JOURNAL_TEMPLATE_UPDATED


async def test_update_template_not_found_raises() -> None:
    _repo, _, service = _fresh_service()
    with pytest.raises(NotFoundError):
        await service.update_template(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), _body())


async def test_delete_template_audits_and_removes() -> None:
    repo, audit, service = _fresh_service()
    created = await service.create_template(uuid.uuid4(), uuid.uuid4(), _body())
    await service.delete_template(uuid.uuid4(), uuid.uuid4(), created.id)
    assert repo.templates == {}
    assert audit.logs[-1]["action"] == FINANCE_JOURNAL_TEMPLATE_DELETED
    with pytest.raises(NotFoundError):
        await service.delete_template(uuid.uuid4(), uuid.uuid4(), created.id)


async def test_generate_creates_draft_stamped_for_idempotency() -> None:
    repo, audit, service = _fresh_service()
    tenant_id = uuid.uuid4()
    created = await service.create_template(tenant_id, uuid.uuid4(), _body())
    fire_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    result = await service.generate(tenant_id, uuid.uuid4(), created.id, fire_at)

    assert result.created is True
    assert result.entry_date == fire_at.date()
    assert result.memo == "Rent for 2026-09-14"
    assert len(repo.created_entries) == 1
    entry = repo.created_entries[0]
    assert entry.status == EntryStatus.DRAFT
    assert entry.source == JOURNAL_SOURCE_TEMPLATE
    assert entry.source_ref == f"{created.id}:2026-09-14"
    assert audit.logs[-1]["action"] == FINANCE_JOURNAL_TEMPLATE_GENERATED


async def test_generate_is_exactly_once_then_created_false() -> None:
    repo, audit, service = _fresh_service()
    tenant_id = uuid.uuid4()
    created = await service.create_template(tenant_id, uuid.uuid4(), _body())
    fire_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)

    first = await service.generate(tenant_id, uuid.uuid4(), created.id, fire_at)
    audit_len = len(audit.logs)
    second = await service.generate(tenant_id, uuid.uuid4(), created.id, fire_at)

    assert first.created is True
    assert second.created is False
    assert second.entry_id is None
    assert len(repo.created_entries) == 1, "replay must never double-book"
    assert len(audit.logs) == audit_len, "idempotent replay must not re-audit"

    # Advance still happened so a fresh run-due scan does not loop.
    assert repo.templates[created.id].next_run_at > fire_at


async def test_generate_renders_offset_into_entry_date() -> None:
    _repo, _audit, service = _fresh_service()
    tenant_id = uuid.uuid4()
    created = await service.create_template(
        tenant_id, uuid.uuid4(), _body(entry_date_offset_days=5)
    )
    result = await service.generate(
        tenant_id, uuid.uuid4(), created.id, datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    )
    assert result.entry_date.isoformat() == "2026-09-19"


async def test_generate_fails_loudly_on_unknown_account() -> None:
    repo, _audit, service = _fresh_service()
    tenant_id = uuid.uuid4()
    created = await service.create_template(tenant_id, uuid.uuid4(), _body())
    repo.account_by_code.pop("6010")
    with pytest.raises(ValidationError, match="unknown account code"):
        await service.generate(tenant_id, uuid.uuid4(), created.id, datetime.now(UTC))


async def test_run_due_generates_due_and_triages_failures() -> None:
    repo, _audit, service = _fresh_service()
    tenant_id = uuid.uuid4()
    fire_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    good = await service.create_template(tenant_id, uuid.uuid4(), _body(name="Good"))
    bad = await service.create_template(
        tenant_id,
        uuid.uuid4(),
        _body(
            name="Bad",
            cron_expression="0 0 15 * *",
            lines=[
                SimpleNamespace(account_code="6010", debit=Decimal("1000"), credit=None),
                SimpleNamespace(account_code="1200", debit=None, credit=Decimal("900")),
                SimpleNamespace(account_code="9999", debit=None, credit=Decimal("100")),
            ],
        ),
    )
    repo.due_templates = [good, bad]

    result = await service.run_due(tenant_id, uuid.uuid4(), fire_at)

    assert result.total_due == 2
    assert [g.template_name for g in result.generated] == ["Good"]
    assert [f.template_name for f in result.failed] == ["Bad"]
    assert "unknown account code" in result.failed[0].reason
    assert result.generated[0].created is True


async def test_generate_and_audit_source_ref_is_fire_stable() -> None:
    """Two service instances (two processes) racing the same fire never double-book."""
    repo_a, _audit_a, service_a = _fresh_service()
    tenant_id = uuid.uuid4()
    template_meta = _body()
    created = await service_a.create_template(tenant_id, uuid.uuid4(), template_meta)

    repo_b, _audit_b, service_b = _fresh_service()
    repo_b.templates = dict(repo_a.templates)
    repo_b.account_by_code = dict(repo_a.account_by_code)
    repo_b.duplicate_source_refs = repo_a.duplicate_source_refs

    fire_at = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    ra = await service_a.generate(tenant_id, uuid.uuid4(), created.id, fire_at)
    rb = await service_b.generate(tenant_id, uuid.uuid4(), created.id, fire_at)

    assert ra.created is True
    assert rb.created is False
    assert len(repo_a.created_entries) + len(repo_b.created_entries) == 1
