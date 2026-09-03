"""Unit tests for the ai-agent account-code suggester (SKY-56/SKY-64).

A fake LlmRouter: no network, no provider. Covers success, abstention on
invalid/unparseable output, out-of-chart code rejection, blank code, bad
confidence, and LLM failure.
"""

from __future__ import annotations

import pytest

from ai_agent.core.providers import LlmCompletion
from ai_agent.features.account_suggest.schemas import AccountOption, SuggestRequest
from ai_agent.features.account_suggest.suggest import (
    _parse_json,
    draft_entry,
    draft_reminder,
    narrate_anomaly,
    suggest,
)


class FakeLlm:
    def __init__(self, *, text: str | None = None, raise_error: bool = False) -> None:
        self._text = text
        self._raise_error = raise_error

    async def complete(self, request: object) -> object:
        if self._raise_error:
            from ai_agent.core.exceptions import AiUnavailableError

            raise AiUnavailableError("boom")
        return LlmCompletion(text=self._text or "{}", model_used="fake-model", latency_ms=10)


def _req() -> SuggestRequest:
    return SuggestRequest(
        description="paid cash 200 to buy furniture",
        accounts=[
            AccountOption(code="1000", name="Cash"),
            AccountOption(code="1500", name="Equipment"),
            AccountOption(code="1100", name="Accounts Receivable"),
        ],
    )


_GOOD = (
    '{"suggested_code": "1500", "suggested_name": "Equipment",'
    ' "confidence": 0.9, "reasoning": "Furniture is a fixed asset.",'
    ' "amount": 200, "side": "debit"}'
)


async def test_suggest_success() -> None:
    result = await suggest(FakeLlm(text=_GOOD), _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.suggested_code == "1500"
    assert result.suggested_name == "Equipment"
    assert result.confidence == pytest.approx(0.9)
    assert result.reasoning == "Furniture is a fixed asset."
    assert result.amount == 200.0
    assert result.side == "debit"
    assert result.model_used == "fake-model"


async def test_suggest_reasoning_defaults_empty_when_absent() -> None:
    llm = FakeLlm(
        text='{"suggested_code": "1500", "suggested_name": "Equipment", "confidence": 0.9}'
    )
    result = await suggest(llm, _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.reasoning == ""
    assert result.amount is None
    assert result.side == "debit"


async def test_suggest_invalid_side_defaults_to_debit() -> None:
    llm = FakeLlm(
        text='{"suggested_code": "1500", "suggested_name": "Equipment",'
        ' "confidence": 0.9, "side": "invalid"}'
    )
    result = await suggest(llm, _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.side == "debit"


async def test_suggest_llm_error_abstains() -> None:
    assert await suggest(FakeLlm(raise_error=True), _req()) is None  # type: ignore[arg-type]


async def test_suggest_unparseable_abstains() -> None:
    assert await suggest(FakeLlm(text="not json"), _req()) is None  # type: ignore[arg-type]


async def test_suggest_out_of_chart_code_rejected() -> None:
    llm = FakeLlm(text='{"suggested_code": "9999", "suggested_name": "Fake", "confidence": 0.9}')
    assert await suggest(llm, _req()) is None  # type: ignore[arg-type]


async def test_suggest_blank_code_abstains() -> None:
    llm = FakeLlm(text='{"suggested_code": "", "suggested_name": "None", "confidence": 0.1}')
    assert await suggest(llm, _req()) is None  # type: ignore[arg-type]


async def test_suggest_bad_confidence_abstains() -> None:
    llm = FakeLlm(
        text='{"suggested_code": "1500", "suggested_name": "Equipment", "confidence": "high"}'
    )
    assert await suggest(llm, _req()) is None  # type: ignore[arg-type]


async def test_suggest_clamps_confidence() -> None:
    llm = FakeLlm(
        text='{"suggested_code": "1500", "suggested_name": "Equipment", "confidence": 1.7}'
    )
    result = await suggest(llm, _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.confidence == 1.0


class TestParse:
    def test_parses_fenced_json(self) -> None:
        payload = _parse_json('```json\n{"a": 1}\n```')
        assert payload == {"a": 1}

    def test_invalid_returns_none(self) -> None:
        assert _parse_json("garbage") is None


# ---------------------------------------------------------------------------
# draft_entry tests
# ---------------------------------------------------------------------------

_BALANCED_DRAFT = (
    '{"lines": ['
    '{"account_code": "1500", "account_name": "Equipment", "amount": 500,'
    ' "side": "debit", "description": "Purchase equipment"},'
    '{"account_code": "1000", "account_name": "Cash", "amount": 500,'
    ' "side": "credit", "description": "Cash payment"}'
    "],"
    ' "explanation": "Debit equipment, credit cash.",'
    ' "confidence": 0.92,'
    ' "reasoning": "Standard purchase entry."}'
)


async def test_draft_entry_balanced() -> None:
    result = await draft_entry(FakeLlm(text=_BALANCED_DRAFT), _req())  # type: ignore[arg-type]
    assert result is not None
    assert len(result.lines) == 2
    assert result.lines[0].account_code == "1500"
    assert result.lines[0].side == "debit"
    assert result.lines[0].amount == pytest.approx(500.0)
    assert result.lines[1].account_code == "1000"
    assert result.lines[1].side == "credit"
    assert result.lines[1].amount == pytest.approx(500.0)
    assert result.confidence == pytest.approx(0.92)
    assert result.explanation == "Debit equipment, credit cash."


async def test_draft_entry_unbalanced_still_returns() -> None:
    text = (
        '{"lines": ['
        '{"account_code": "1500", "account_name": "Equipment", "amount": 600,'
        ' "side": "debit", "description": ""},'
        '{"account_code": "1000", "account_name": "Cash", "amount": 500,'
        ' "side": "credit", "description": ""}'
        "],"
        ' "explanation": "Test", "confidence": 0.8, "reasoning": "Test"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert len(result.lines) == 2


async def test_draft_entry_out_of_chart_lines_dropped() -> None:
    text = (
        '{"lines": ['
        '{"account_code": "1500", "account_name": "Equipment", "amount": 500,'
        ' "side": "debit", "description": ""},'
        '{"account_code": "9999", "account_name": "Fake", "amount": 500,'
        ' "side": "credit", "description": ""}'
        "],"
        ' "explanation": "Test", "confidence": 0.8, "reasoning": "Test"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert len(result.lines) == 1
    assert result.lines[0].account_code == "1500"


async def test_draft_entry_blank_lines_return_none() -> None:
    text = '{"lines": [], "explanation": "T", "confidence": 0.8, "reasoning": "T"}'
    assert await draft_entry(FakeLlm(text=text), _req()) is None  # type: ignore[arg-type]


async def test_draft_entry_no_lines_key_return_none() -> None:
    text = '{"explanation": "T", "confidence": 0.8, "reasoning": "T"}'
    assert await draft_entry(FakeLlm(text=text), _req()) is None  # type: ignore[arg-type]


async def test_draft_entry_invalid_amount_skipped() -> None:
    text = (
        '{"lines": ['
        '{"account_code": "1500", "account_name": "Equipment", "amount": -10,'
        ' "side": "debit", "description": ""},'
        '{"account_code": "1000", "account_name": "Cash", "amount": 500,'
        ' "side": "credit", "description": ""}'
        "],"
        ' "explanation": "T", "confidence": 0.8, "reasoning": "T"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert len(result.lines) == 1
    assert result.lines[0].account_code == "1000"


async def test_draft_entry_invalid_side_defaults_debit() -> None:
    text = (
        '{"lines": ['
        '{"account_code": "1500", "account_name": "Equipment", "amount": 500,'
        ' "side": "bogus", "description": ""},'
        '{"account_code": "1000", "account_name": "Cash", "amount": 500,'
        ' "side": "credit", "description": ""}'
        "],"
        ' "explanation": "T", "confidence": 0.8, "reasoning": "T"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.lines[0].side == "debit"


async def test_draft_entry_invalid_confidence_defaults_05() -> None:
    text = (
        '{"lines": ['
        '{"account_code": "1500", "account_name": "Equipment", "amount": 500,'
        ' "side": "debit", "description": ""},'
        '{"account_code": "1000", "account_name": "Cash", "amount": 500,'
        ' "side": "credit", "description": ""}'
        "],"
        ' "explanation": "T", "confidence": "high", "reasoning": "T"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.confidence == pytest.approx(0.5)


async def test_draft_entry_llm_error_abstains() -> None:
    assert await draft_entry(FakeLlm(raise_error=True), _req()) is None  # type: ignore[arg-type]


async def test_draft_entry_unparseable_abstains() -> None:
    assert await draft_entry(FakeLlm(text="not json"), _req()) is None  # type: ignore[arg-type]


async def test_draft_entry_non_dict_line_skipped() -> None:
    text = (
        '{"lines": ["bad",'
        ' {"account_code": "1500", "account_name": "Equipment", "amount": 500,'
        ' "side": "debit", "description": ""}],'
        ' "explanation": "T", "confidence": 0.8, "reasoning": "T"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert len(result.lines) == 1


async def test_draft_entry_missing_name_filled_from_chart() -> None:
    text = (
        '{"lines": ['
        '{"account_code": "1500", "account_name": "", "amount": 500,'
        ' "side": "debit", "description": ""},'
        '{"account_code": "1000", "account_name": "Cash", "amount": 500,'
        ' "side": "credit", "description": ""}'
        "],"
        ' "explanation": "T", "confidence": 0.8, "reasoning": "T"}'
    )
    result = await draft_entry(FakeLlm(text=text), _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.lines[0].account_name == "Equipment"


# ---------------------------------------------------------------------------
# narrate_anomaly tests
# ---------------------------------------------------------------------------

_NARRATION = '{"narration": "An unusual duplicate entry was detected.", "confidence": 0.9}'


async def test_narrate_anomaly_returns_narration() -> None:
    result = await narrate_anomaly(
        FakeLlm(text=_NARRATION),  # type: ignore[arg-type]
        anomaly_type="duplicate_entry",
        description="Two identical journal entries posted on the same day.",
        severity="medium",
    )
    assert result is not None
    assert result["narration"] == "An unusual duplicate entry was detected."
    assert result["model_used"] == "fake-model"


async def test_narrate_anomaly_empty_narration_returns_none() -> None:
    text = '{"narration": "", "confidence": 0.9}'
    result = await narrate_anomaly(
        FakeLlm(text=text),  # type: ignore[arg-type]
        anomaly_type="duplicate_entry",
        description="Test",
        severity="low",
    )
    assert result is None


async def test_narrate_anomaly_llm_error_returns_none() -> None:
    result = await narrate_anomaly(
        FakeLlm(raise_error=True),  # type: ignore[arg-type]
        anomaly_type="duplicate_entry",
        description="Test",
        severity="low",
    )
    assert result is None


async def test_narrate_anomaly_unparseable_returns_none() -> None:
    result = await narrate_anomaly(
        FakeLlm(text="not json"),  # type: ignore[arg-type]
        anomaly_type="duplicate_entry",
        description="Test",
        severity="low",
    )
    assert result is None


# ---------------------------------------------------------------------------
# draft_reminder tests
# ---------------------------------------------------------------------------

_REMINDER = (
    '{"subject": "Payment Reminder - Invoice INV-001",'
    ' "body": "Please pay your overdue invoice.",'
    ' "tone": "polite"}'
)


async def test_draft_reminder_returns_fields() -> None:
    result = await draft_reminder(
        FakeLlm(text=_REMINDER),  # type: ignore[arg-type]
        customer_name="Acme Corp",
        invoice_number="INV-001",
        amount=1500.0,
        days_overdue=15,
        tone="polite",
    )
    assert result is not None
    assert result["subject"] == "Payment Reminder - Invoice INV-001"
    assert result["body"] == "Please pay your overdue invoice."
    assert result["tone"] == "polite"
    assert result["model_used"] == "fake-model"


async def test_draft_reminder_missing_subject_returns_none() -> None:
    text = '{"subject": "", "body": "Please pay.", "tone": "polite"}'
    result = await draft_reminder(
        FakeLlm(text=text),  # type: ignore[arg-type]
        customer_name="Acme",
        invoice_number="INV-002",
        amount=500.0,
        days_overdue=5,
        tone="polite",
    )
    assert result is None


async def test_draft_reminder_missing_body_returns_none() -> None:
    text = '{"subject": "Reminder", "body": "", "tone": "polite"}'
    result = await draft_reminder(
        FakeLlm(text=text),  # type: ignore[arg-type]
        customer_name="Acme",
        invoice_number="INV-002",
        amount=500.0,
        days_overdue=5,
        tone="polite",
    )
    assert result is None


async def test_draft_reminder_llm_error_returns_none() -> None:
    result = await draft_reminder(
        FakeLlm(raise_error=True),  # type: ignore[arg-type]
        customer_name="Acme",
        invoice_number="INV-002",
        amount=500.0,
        days_overdue=5,
        tone="polite",
    )
    assert result is None


async def test_draft_reminder_unparseable_returns_none() -> None:
    result = await draft_reminder(
        FakeLlm(text="not json"),  # type: ignore[arg-type]
        customer_name="Acme",
        invoice_number="INV-002",
        amount=500.0,
        days_overdue=5,
        tone="polite",
    )
    assert result is None


async def test_draft_reminder_none_customer_name() -> None:
    text = '{"subject": "Reminder", "body": "Please remit payment.", "tone": "firm"}'
    result = await draft_reminder(
        FakeLlm(text=text),  # type: ignore[arg-type]
        customer_name=None,
        invoice_number="INV-003",
        amount=2000.0,
        days_overdue=45,
        tone="firm",
    )
    assert result is not None
    assert result["tone"] == "firm"
