"""Unit tests for the finance automation service thin layer (SKY-56/SKY-64).

Focus on the service's own decision logic (which the repo does NOT cover):
the reversal guards (only posted, not-already-reversed entries reverse) and the
settings read/write path. Repository-level aggregation is covered by the
integration suite against real Postgres (test_finance_automation.py).
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.core.exceptions import AiServiceUnavailableError
from core.domain.entities import (
    AccountCodeSuggestion,
    ChartOfAccount,
    JournalEntry,
)
from core.domain.value_objects import AccountType, EntryStatus
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
    repo.journal_entry = _entry(EntryStatus.POSTED, reversal_entry_id=object())
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
