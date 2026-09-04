"""Unit tests for the finance automation service thin layer (SKY-56/SKY-64).

Focus on the service's own decision logic (which the repo does NOT cover):
the reversal guards (only posted, not-already-reversed entries reverse) and the
settings read/write path. Repository-level aggregation is covered by the
integration suite against real Postgres (test_finance_automation.py).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.core.audit_events import (
    FINANCE_AI_ANOMALY_NARRATED,
    FINANCE_AI_DRAFT_GENERATED,
    FINANCE_AI_REMINDER_GENERATED,
)
from core.core.exceptions import AiServiceUnavailableError
from core.domain.entities import (
    AccountCodeSuggestion,
    AiFinanceAnomaly,
    ChartOfAccount,
    Invoice,
    JournalEntry,
)
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus
from core.features.finance.automation import FinanceAutomationService
from skyrict_common.exceptions import NotFoundError


class StubRepo:
    """Records calls; returns canned responses for the fields under test."""

    def __init__(self) -> None:
        self.journal_entry: JournalEntry | None = None
        self.reversed_calls: list[tuple[object, object, object, object]] = []
        self.setting_value: str | None = None
        self.setting_writes: list[tuple[object, str, str]] = []
        self.accounts: list[ChartOfAccount] = []
        self.keyword_result: AccountCodeSuggestion | None = None
        self.keyword_calls = 0
        # FIN-AI-001 stub state
        self.anomaly: AiFinanceAnomaly | None = None
        self.anomaly_calls: list[tuple[object, object]] = []
        self.invoice: Invoice | None = None
        self.invoice_calls: list[tuple[object, object]] = []
        self.overdue_invoices: list[Invoice] = []
        self.overdue_calls: list[object] = []

    async def get_journal_entry(self, entry_id, tenant_id):
        return self.journal_entry

    async def reverse_journal_entry(self, entry_id, tenant_id, *, reversed_by_user_id, reversed_at):
        self.reversed_calls.append((entry_id, tenant_id, reversed_by_user_id, reversed_at))
        return self.journal_entry

    async def get_tenant_setting(self, tenant_id, key):
        return SimpleNamespace(value=self.setting_value) if self.setting_value is not None else None

    async def upsert_tenant_setting(self, tenant_id, key, value):
        self.setting_writes.append((tenant_id, key, value))
        self.setting_value = value
        return SimpleNamespace(value=value)

    async def list_accounts(self, tenant_id):
        return self.accounts

    async def suggest_account_code(self, tenant_id, description):
        self.keyword_calls += 1
        if self.keyword_result is not None:
            return self.keyword_result
        return AccountCodeSuggestion(
            description=description, suggested_code="", suggested_name="", confidence=Decimal("0")
        )

    async def upsert_ai_suggestion(self, tenant_id, suggestion):
        pass

    # --- FIN-AI-001 additions ---

    async def get_ai_anomaly(self, tenant_id, anomaly_id):
        self.anomaly_calls.append((tenant_id, anomaly_id))
        return self.anomaly

    async def get_invoice_by_id(self, tenant_id, invoice_id):
        self.invoice_calls.append((tenant_id, invoice_id))
        return self.invoice

    async def list_invoices_overdue(self, tenant_id):
        self.overdue_calls.append(tenant_id)
        return self.overdue_invoices


class RecordingAudit:
    def __init__(self) -> None:
        self.logs: list[dict[str, object]] = []

    async def log(self, **kwargs: object) -> None:
        self.logs.append(kwargs)


def _entry(status: EntryStatus, reversal_entry_id=None) -> JournalEntry:
    return JournalEntry(
        tenant_id=object(),  # type: ignore[arg-type]  # placeholder, unused by service
        entry_date="2026-01-01",  # type: ignore[arg-type]
        memo="test",
        status=status,
        source="manual",
        source_ref=None,
        reversal_entry_id=reversal_entry_id,
    )


async def test_reverse_requires_existing_entry() -> None:
    repo = StubRepo()
    repo.journal_entry = None
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    with pytest.raises(NotFoundError):
        await svc.reverse_journal_entry(tenant_id=object(), user_id=object(), entry_id=object())
    assert repo.reversed_calls == []


async def test_reverse_requires_posted_entry() -> None:
    repo = StubRepo()
    repo.journal_entry = _entry(EntryStatus.DRAFT)
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    with pytest.raises(NotFoundError):
        await svc.reverse_journal_entry(tenant_id=object(), user_id=object(), entry_id=object())
    assert repo.reversed_calls == []


async def test_reverse_rejects_already_reversed() -> None:
    repo = StubRepo()
    repo.journal_entry = _entry(EntryStatus.REVERSED)
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    with pytest.raises(NotFoundError):
        await svc.reverse_journal_entry(tenant_id=object(), user_id=object(), entry_id=object())
    assert repo.reversed_calls == []


async def test_reverse_succeeds_on_posted_unreversed_and_audits() -> None:
    repo = StubRepo()
    entry = _entry(EntryStatus.POSTED, reversal_entry_id=None)
    repo.journal_entry = entry
    audit = RecordingAudit()
    svc = FinanceAutomationService(repo=repo, audit=audit)
    result = await svc.reverse_journal_entry(
        tenant_id=object(), user_id=object(), entry_id=object()
    )
    assert result is entry
    assert len(repo.reversed_calls) == 1
    assert len(audit.logs) == 1


async def test_settings_default_when_unset() -> None:
    repo = StubRepo()
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    settings = await svc.get_settings(object())
    assert settings.working_capital_threshold == Decimal("1.5")


async def test_settings_roundtrip_persists_threshold() -> None:
    repo = StubRepo()
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    got = await svc.put_settings(object(), 2.0)
    assert got.working_capital_threshold == Decimal("2.0")
    persisted = await svc.get_settings(object())
    assert persisted.working_capital_threshold == Decimal("2.0")
    assert len(repo.setting_writes) == 1


def _account(code: str, name: str) -> ChartOfAccount:
    return ChartOfAccount(
        tenant_id=object(),
        code=code,
        name=name,
        account_type=AccountType.ASSET,
    )  # type: ignore[arg-type]


async def test_suggest_uses_ai_when_available() -> None:
    repo = StubRepo()
    repo.accounts = [_account("1000", "Cash"), _account("1500", "Equipment")]
    repo.keyword_result = AccountCodeSuggestion(
        description="d", suggested_code="1000", suggested_name="Cash", confidence=Decimal("1")
    )

    async def ai_suggest(description, accounts):
        return AccountCodeSuggestion(
            description=description,
            suggested_code="1500",
            suggested_name="Equipment",
            confidence=Decimal("0.9"),
        )

    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit(), ai_suggest=ai_suggest)
    result = await svc.suggest_account_code(object(), "buy furniture")
    assert result.suggested_code == "1500"
    assert repo.keyword_calls == 0


async def test_suggest_falls_back_when_ai_unavailable() -> None:
    repo = StubRepo()
    repo.accounts = [_account("1000", "Cash"), _account("1001", "Rent")]
    repo.keyword_result = AccountCodeSuggestion(
        description="d", suggested_code="1001", suggested_name="Rent", confidence=Decimal("3")
    )

    async def ai_suggest(description, accounts):
        raise AiServiceUnavailableError("down")

    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit(), ai_suggest=ai_suggest)
    result = await svc.suggest_account_code(object(), "rent for office")
    assert result.suggested_code == "1001"
    assert repo.keyword_calls == 1


async def test_suggest_without_ai_uses_keyword() -> None:
    repo = StubRepo()
    repo.accounts = [_account("1000", "Cash")]
    repo.keyword_result = AccountCodeSuggestion(
        description="d", suggested_code="1000", suggested_name="Cash", confidence=Decimal("1")
    )
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    result = await svc.suggest_account_code(object(), "x")
    assert result.suggested_code == "1000"


async def test_suggest_empty_when_no_accounts() -> None:
    repo = StubRepo()
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())
    result = await svc.suggest_account_code(object(), "x")
    assert result.suggested_code == ""


# ---------------------------------------------------------------------------
# FIN-AI-001 helpers
# ---------------------------------------------------------------------------


def _anomaly() -> AiFinanceAnomaly:
    return AiFinanceAnomaly(
        tenant_id=uuid.uuid4(),
        entity_type="journal_entry",
        entity_id=uuid.uuid4(),
        anomaly_type="duplicate_entry",
        severity="medium",
        description="Two identical journal entries posted on the same day.",
    )


def _invoice(*, due_offset: int = -15, total: Decimal = Decimal("1500")) -> Invoice:
    today = date.today()
    return Invoice(
        tenant_id=uuid.uuid4(),
        invoice_number="INV-001",
        customer_id=uuid.uuid4(),
        invoice_date=today - timedelta(days=60),
        due_date=today + timedelta(days=due_offset),
        status=InvoiceStatus.ISSUED,
        total=total,
        source="manual",
        source_ref=None,
        lines=(),
    )


_TENANT = uuid.uuid4()
_ENTRY_ID = uuid.uuid4()
_ANOMALY_ID = uuid.uuid4()
_INVOICE_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# draft_journal_entry tests
# ---------------------------------------------------------------------------


async def test_draft_journal_entry_returns_balanced_2_line_draft() -> None:
    repo = StubRepo()
    repo.keyword_result = AccountCodeSuggestion(
        description="buy furniture",
        suggested_code="1500",
        suggested_name="Equipment",
        confidence=Decimal("0.9"),
        contra_code="1000",
        contra_name="Cash",
    )
    audit = RecordingAudit()
    svc = FinanceAutomationService(repo=repo, audit=audit)

    draft = await svc.draft_journal_entry(_TENANT, "buy furniture")

    assert len(draft.lines) == 2
    debit = draft.lines[0]
    credit = draft.lines[1]
    assert debit.side == "debit"
    assert debit.account_code == "1500"
    assert credit.side == "credit"
    assert credit.account_code == "1000"
    assert debit.amount == Decimal("0")
    assert credit.amount == Decimal("0")
    assert repo.keyword_calls == 1

    assert len(audit.logs) == 1
    assert audit.logs[0]["action"] == FINANCE_AI_DRAFT_GENERATED


async def test_draft_journal_entry_uses_keyword_when_no_ai_suggest() -> None:
    repo = StubRepo()
    repo.keyword_result = AccountCodeSuggestion(
        description="d",
        suggested_code="2000",
        suggested_name="Accounts Payable",
        confidence=Decimal("0.7"),
        contra_code="1000",
        contra_name="Cash",
    )
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    draft = await svc.draft_journal_entry(_TENANT, "pay supplier")

    assert draft.lines[0].account_code == "2000"
    assert draft.lines[0].side == "debit"
    assert draft.lines[1].account_code == "1000"
    assert draft.lines[1].side == "credit"
    assert draft.reasoning == "Deterministic fallback — AI service unavailable"


async def test_draft_journal_entry_no_contra_falls_back_to_suggested() -> None:
    repo = StubRepo()
    repo.keyword_result = AccountCodeSuggestion(
        description="d",
        suggested_code="1500",
        suggested_name="Equipment",
        confidence=Decimal("0.9"),
    )
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    draft = await svc.draft_journal_entry(_TENANT, "buy furniture")

    assert draft.lines[0].account_code == "1500"
    assert draft.lines[1].account_code == "1500"


# ---------------------------------------------------------------------------
# narrate_anomaly tests
# ---------------------------------------------------------------------------


async def test_narrate_anomaly_returns_narration_and_audits() -> None:
    repo = StubRepo()
    anomaly = _anomaly()
    repo.anomaly = anomaly
    audit = RecordingAudit()
    svc = FinanceAutomationService(repo=repo, audit=audit)

    result = await svc.narrate_anomaly(_TENANT, _ANOMALY_ID)

    assert result["narration"] == (
        f"Anomaly detected: {anomaly.anomaly_type} — {anomaly.description}"
    )
    assert len(audit.logs) == 1
    assert audit.logs[0]["action"] == FINANCE_AI_ANOMALY_NARRATED
    assert repo.anomaly_calls == [(_TENANT, _ANOMALY_ID)]


async def test_narrate_anomaly_raises_when_missing() -> None:
    repo = StubRepo()
    repo.anomaly = None
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    with pytest.raises(NotFoundError):
        await svc.narrate_anomaly(_TENANT, _ANOMALY_ID)


# ---------------------------------------------------------------------------
# generate_reminder tests
# ---------------------------------------------------------------------------


async def test_generate_reminder_polite_tone() -> None:
    repo = StubRepo()
    invoice = _invoice(due_offset=-10)
    repo.invoice = invoice
    audit = RecordingAudit()
    svc = FinanceAutomationService(repo=repo, audit=audit)

    reminder = await svc.generate_reminder(_TENANT, _INVOICE_ID)

    assert reminder.tone == "polite"
    assert reminder.invoice_number == invoice.invoice_number
    assert reminder.amount == invoice.total
    assert reminder.days_overdue == 10
    assert len(audit.logs) == 1
    assert audit.logs[0]["action"] == FINANCE_AI_REMINDER_GENERATED


async def test_generate_reminder_firm_tone() -> None:
    repo = StubRepo()
    invoice = _invoice(due_offset=-45)
    repo.invoice = invoice
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    reminder = await svc.generate_reminder(_TENANT, _INVOICE_ID)

    assert reminder.tone == "firm"


async def test_generate_reminder_final_tone() -> None:
    repo = StubRepo()
    invoice = _invoice(due_offset=-90)
    repo.invoice = invoice
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    reminder = await svc.generate_reminder(_TENANT, _INVOICE_ID)

    assert reminder.tone == "final"


async def test_generate_reminder_raises_when_invoice_missing() -> None:
    repo = StubRepo()
    repo.invoice = None
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    with pytest.raises(NotFoundError):
        await svc.generate_reminder(_TENANT, _INVOICE_ID)


# ---------------------------------------------------------------------------
# batch_reminders tests
# ---------------------------------------------------------------------------


async def test_batch_reminders_returns_one_per_overdue_invoice() -> None:
    repo = StubRepo()
    inv1 = _invoice(due_offset=-10, total=Decimal("100"))
    inv2 = _invoice(due_offset=-50, total=Decimal("200"))
    repo.overdue_invoices = [inv1, inv2]
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    reminders = await svc.batch_reminders(_TENANT)

    assert len(reminders) == 2
    assert reminders[0].tone == "polite"
    assert reminders[1].tone == "firm"
    assert repo.overdue_calls == [_TENANT]


async def test_batch_reminders_no_audit() -> None:
    repo = StubRepo()
    repo.overdue_invoices = [_invoice(due_offset=-10)]
    audit = RecordingAudit()
    svc = FinanceAutomationService(repo=repo, audit=audit)

    await svc.batch_reminders(_TENANT)

    assert len(audit.logs) == 0


async def test_batch_reminders_empty_list() -> None:
    repo = StubRepo()
    repo.overdue_invoices = []
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    reminders = await svc.batch_reminders(_TENANT)

    assert reminders == []
