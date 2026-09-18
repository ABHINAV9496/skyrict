"""Unit tests for the finance automation service thin layer (SKY-56/SKY-64).

Focus on the service's own decision logic (which the repo does NOT cover):
the reversal guards (only posted, not-already-reversed entries reverse) and the
settings read/write path. Repository-level aggregation is covered by the
integration suite against real Postgres (test_finance_automation.py).
"""

from __future__ import annotations

import time
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
    AiFinanceSuggestion,
    AnomalyNarration,
    ChartOfAccount,
    Invoice,
    JournalEntry,
    ReminderDraft,
)
from core.domain.value_objects import AccountType, EntryStatus, InvoiceStatus
from core.features.finance.automation import (
    FinanceAutomationService,
    extract_vendor_ref,
)
from skyrict_common.exceptions import NotFoundError


class StubRepo:
    """Records calls; returns canned responses for the fields under test."""

    def __init__(self) -> None:
        self.journal_entry: JournalEntry | None = None
        self.reversed_calls: list[tuple[object, object, object, object]] = []
        self.settings: dict[str, str] = {}
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
        # SKY-67 acceptance telemetry stub state
        self.reviewed_suggestion: AiFinanceSuggestion | None = None
        self.review_calls: list[tuple[object, object, bool]] = []
        self.acceptance_counts: list[tuple[str, int, int]] = []
        self.quality_upserts: list[object] = []
        # C6 numbering-scheme stub state
        self.invoice_count = 0

    async def get_journal_entry(self, entry_id, tenant_id):
        return self.journal_entry

    async def reverse_journal_entry(self, entry_id, tenant_id, *, reversed_by_user_id, reversed_at):
        self.reversed_calls.append((entry_id, tenant_id, reversed_by_user_id, reversed_at))
        return self.journal_entry

    async def get_tenant_setting(self, tenant_id, key):
        value = self.settings.get(key)
        return SimpleNamespace(value=value) if value is not None else None

    async def upsert_tenant_setting(self, tenant_id, key, value):
        self.setting_writes.append((tenant_id, key, value))
        self.settings[key] = value
        return SimpleNamespace(value=value)

    async def count_invoices_since(self, tenant_id, since):
        return self.invoice_count

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

    async def review_ai_suggestion(self, tenant_id, suggestion_id, *, accepted):
        self.review_calls.append((tenant_id, suggestion_id, accepted))
        return self.reviewed_suggestion

    async def suggestion_acceptance_counts(self, tenant_id, window_days):
        return self.acceptance_counts

    async def upsert_ai_quality_score(self, tenant_id, score):
        self.quality_upserts.append(score)
        return score

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


async def test_settings_roundtrip_persists_numbering_scheme() -> None:
    repo = StubRepo()
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    got = await svc.put_settings(
        object(), Decimal("1.5"), invoice_numbering_scheme="INV-2026-######"
    )

    assert got.invoice_numbering_scheme == "INV-2026-######"
    assert any(key == "invoice_numbering_scheme" for _, key, _ in repo.setting_writes)


async def test_settings_put_without_scheme_preserves_existing() -> None:
    repo = StubRepo()
    repo.settings["invoice_numbering_scheme"] = "FAC-2026-#####"
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    got = await svc.put_settings(object(), Decimal("2.0"))

    assert got.invoice_numbering_scheme == "FAC-2026-#####"
    assert len(repo.setting_writes) == 1  # only the threshold write happened


async def test_recommend_numbering_scheme_scales_width_with_volume() -> None:
    base = date(2026, 6, 1)
    for volume, expected_width, expected_scheme in [
        (500, 5, "INV-2026-#####"),
        (50_000, 6, "INV-2026-######"),
        (150_000, 7, "INV-2026-#######"),
    ]:
        repo = StubRepo()
        repo.invoice_count = volume
        svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

        got = await svc.recommend_numbering_scheme(object(), today=base)

        assert got.seq_width == expected_width
        assert got.scheme == expected_scheme
        assert "INV" in got.prefix


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
    assert draft.fallback is True


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


async def test_narrate_anomaly_uses_ai_when_cites_figure() -> None:
    repo = StubRepo()
    repo.anomaly = _anomaly()
    audit = RecordingAudit()

    async def ai_narrate(anomaly_type, description, severity):
        return AnomalyNarration(
            narration="Duplicate entry flagged - both posts total 1,200. Review...",
            model_used="gpt-test",
        )

    svc = FinanceAutomationService(repo=repo, audit=audit, ai_narrate=ai_narrate)
    result = await svc.narrate_anomaly(_TENANT, _ANOMALY_ID)

    assert result["narration"].startswith("Duplicate entry flagged")
    assert result["model_used"] == "gpt-test"
    assert audit.logs[0]["details"]["model_used"] == "gpt-test"


async def test_narrate_anomaly_falls_back_when_ai_omits_figure() -> None:
    repo = StubRepo()
    anomaly = _anomaly()
    repo.anomaly = anomaly

    async def ai_narrate(anomaly_type, description, severity):
        return AnomalyNarration(narration="A duplicate entry was detected.", model_used="gpt-test")

    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit(), ai_narrate=ai_narrate)
    result = await svc.narrate_anomaly(_TENANT, _ANOMALY_ID)

    assert result["model_used"] == ""
    assert result["narration"] == (
        f"Anomaly detected: {anomaly.anomaly_type} — {anomaly.description}"
    )


async def test_narrate_anomaly_falls_back_when_ai_fails() -> None:
    repo = StubRepo()
    anomaly = _anomaly()
    repo.anomaly = anomaly

    async def ai_narrate(anomaly_type, description, severity):
        raise AiServiceUnavailableError("down")

    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit(), ai_narrate=ai_narrate)
    result = await svc.narrate_anomaly(_TENANT, _ANOMALY_ID)

    assert result["model_used"] == ""
    assert "Anomaly detected" in result["narration"]


async def test_narrate_anomaly_falls_back_when_ai_abstains() -> None:
    repo = StubRepo()
    repo.anomaly = _anomaly()

    async def ai_narrate(anomaly_type, description, severity):
        return None

    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit(), ai_narrate=ai_narrate)
    result = await svc.narrate_anomaly(_TENANT, _ANOMALY_ID)

    assert result["model_used"] == ""
    assert "Anomaly detected" in result["narration"]


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


async def test_generate_reminder_uses_ai() -> None:
    repo = StubRepo()
    invoice = _invoice(due_offset=-10, total=Decimal("1500"))
    repo.invoice = invoice
    audit = RecordingAudit()

    async def ai_remind(customer_name, invoice_number, amount, days_overdue, tone):
        return ReminderDraft(
            invoice_number=invoice_number,
            customer_name="Acme Corp",
            amount=amount,
            days_overdue=days_overdue,
            tone=tone,
            subject=f"Overdue Invoice {invoice_number}",
            body="Please remit payment for invoice INV-001 totaling 1,500.",
            model_used="gpt-test",
        )

    svc = FinanceAutomationService(repo=repo, audit=audit, ai_remind=ai_remind)
    reminder = await svc.generate_reminder(_TENANT, _INVOICE_ID)

    assert reminder.customer_name == "Acme Corp"
    assert reminder.subject == "Overdue Invoice INV-001"
    assert reminder.model_used == "gpt-test"
    assert audit.logs[0]["details"]["model_used"] == "gpt-test"


async def test_generate_reminder_falls_back_when_ai_fails() -> None:
    repo = StubRepo()
    repo.invoice = _invoice(due_offset=-10, total=Decimal("1500"))

    async def ai_remind(customer_name, invoice_number, amount, days_overdue, tone):
        raise AiServiceUnavailableError("down")

    audit = RecordingAudit()
    svc = FinanceAutomationService(repo=repo, audit=audit, ai_remind=ai_remind)
    reminder = await svc.generate_reminder(_TENANT, _INVOICE_ID)

    assert reminder.model_used == ""
    assert "Payment Reminder" in reminder.subject
    assert audit.logs[0]["details"]["model_used"] == ""


async def test_generate_reminder_falls_back_when_ai_returns_empty() -> None:
    repo = StubRepo()
    repo.invoice = _invoice(due_offset=-10, total=Decimal("1500"))

    async def ai_remind(customer_name, invoice_number, amount, days_overdue, tone):
        return None

    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit(), ai_remind=ai_remind)
    reminder = await svc.generate_reminder(_TENANT, _INVOICE_ID)

    assert reminder.model_used == ""
    assert "Payment Reminder" in reminder.subject


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


async def test_batch_reminders_uses_ai_and_audits_ai_generated() -> None:
    repo = StubRepo()
    inv1 = _invoice(due_offset=-10, total=Decimal("100"))
    repo.overdue_invoices = [inv1]
    audit = RecordingAudit()

    async def ai_remind(customer_name, invoice_number, amount, days_overdue, tone):
        return ReminderDraft(
            invoice_number=invoice_number,
            customer_name=None,
            amount=amount,
            days_overdue=days_overdue,
            tone=tone,
            subject=f"Overdue {invoice_number}",
            body="Please pay now, thanks.",
            model_used="gpt-test",
        )

    svc = FinanceAutomationService(repo=repo, audit=audit, ai_remind=ai_remind)
    reminders = await svc.batch_reminders(_TENANT)

    assert reminders[0].model_used == "gpt-test"
    assert len(audit.logs) == 1
    assert audit.logs[0]["action"] == FINANCE_AI_REMINDER_GENERATED


async def test_batch_reminders_falls_back_per_invoice_when_ai_fails() -> None:
    repo = StubRepo()
    repo.overdue_invoices = [_invoice(due_offset=-10)]
    audit = RecordingAudit()

    async def ai_remind(customer_name, invoice_number, amount, days_overdue, tone):
        raise AiServiceUnavailableError("down")

    svc = FinanceAutomationService(repo=repo, audit=audit, ai_remind=ai_remind)
    reminders = await svc.batch_reminders(_TENANT)

    assert reminders[0].model_used == ""
    assert len(audit.logs) == 0


async def test_accept_suggestion_marks_accepted() -> None:
    repo = StubRepo()
    repo.reviewed_suggestion = AiFinanceSuggestion(
        tenant_id=_TENANT,
        description="rent",
        suggested_code="5000",
        suggested_name="Rent Expense",
        confidence=Decimal("0.9"),
        status="accepted",
        id=uuid.uuid4(),
    )
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    result = await svc.accept_suggestion(_TENANT, uuid.uuid4())

    assert result.status == "accepted"
    assert repo.review_calls == [(_TENANT, repo.review_calls[0][1], True)]


async def test_dismiss_suggestion_marks_dismissed() -> None:
    repo = StubRepo()
    repo.reviewed_suggestion = AiFinanceSuggestion(
        tenant_id=_TENANT,
        description="rent",
        suggested_code="5000",
        suggested_name="Rent Expense",
        confidence=Decimal("0.9"),
        status="dismissed",
        id=uuid.uuid4(),
    )
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    result = await svc.dismiss_suggestion(_TENANT, uuid.uuid4())

    assert result.status == "dismissed"
    assert repo.review_calls[0][2] is False


async def test_accept_suggestion_raises_when_missing() -> None:
    repo = StubRepo()
    repo.reviewed_suggestion = None
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    with pytest.raises(NotFoundError):
        await svc.accept_suggestion(_TENANT, uuid.uuid4())


async def test_suggestion_quality_computes_rates_and_persists_scores() -> None:
    repo = StubRepo()
    repo.acceptance_counts = [
        ("account_suggest", 2, 8),  # 20% -> below threshold
        ("draft_entry", 9, 1),  # 90% -> above threshold
    ]
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    result = await svc.suggestion_quality(_TENANT, window_days=30)

    assert len(result.features) == 2
    assert len(repo.quality_upserts) == 2
    scores = {s.feature: s for s in result.features}
    assert scores["account_suggest"].acceptance_rate == Decimal("0.2")
    assert scores["account_suggest"].below_threshold is True
    assert scores["draft_entry"].below_threshold is False
    assert result.overall_acceptance_rate == Decimal("0.55")  # 11/20
    assert result.low_quality is True
    assert result.window_days == 30


async def test_suggestion_quality_no_signal_is_not_low_quality() -> None:
    repo = StubRepo()
    repo.acceptance_counts = []
    svc = FinanceAutomationService(repo=repo, audit=RecordingAudit())

    result = await svc.suggestion_quality(_TENANT, window_days=30)

    assert result.features == []
    assert result.overall_acceptance_rate is None
    assert result.low_quality is False
    assert repo.quality_upserts == []


# ---------------------------------------------------------------------------
# B23: vendor-invoice-number extraction
# ---------------------------------------------------------------------------


def test_extract_vendor_ref_invoice_forms() -> None:
    assert extract_vendor_ref("Payment for Invoice INV-2024-0117") == "2024-0117"
    assert extract_vendor_ref("inv: ACR-8821") == "ACR-8821"
    assert extract_vendor_ref("reference #VB-1033") == "VB-1033"
    assert extract_vendor_ref("PO-7777") == "7777"


def test_extract_vendor_ref_no_match() -> None:
    assert extract_vendor_ref("thank you") is None
    assert extract_vendor_ref("") is None
    assert extract_vendor_ref("   ") is None


def test_extract_vendor_ref_separator_variants() -> None:
    assert extract_vendor_ref("inv   -   AB-12345") == "AB-12345"
    assert extract_vendor_ref("ref :  X-9012") == "X-9012"
    assert extract_vendor_ref("invoice#  C-7007") == "C-7007"
    assert extract_vendor_ref("po \t D-4040") == "D-4040"


def test_extract_vendor_ref_linear_on_space_flood() -> None:
    """ReDoS regression: separators must not backtrack quadratically on 'inv ' + spaces."""
    start = time.monotonic()
    assert extract_vendor_ref("inv" + " " * 40000) is None
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"regex backtracked quadratically: {elapsed:.3f}s"
