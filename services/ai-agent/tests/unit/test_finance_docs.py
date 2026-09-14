"""Unit tests for the finance-docs LLM primitives (FIN-AI-004)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent.features.finance_docs.generate import (
    answer_question,
    generate_tax_summary,
    narrate_audit,
)


def _completion(text: str, model_used: str = "test-model") -> MagicMock:
    completion = MagicMock()
    completion.text = text
    completion.model_used = model_used
    return completion


def _router(completion: MagicMock) -> MagicMock:
    router = MagicMock()
    router.complete = AsyncMock(return_value=completion)
    return router


_PERIOD = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "FY 2025-Q1",
    "start_date": "2025-01-01",
    "end_date": "2025-03-31",
    "is_closed": False,
}

_ENTRIES = [
    {
        "id": "22222222-2222-2222-2222-222222222222",
        "entry_date": "2025-01-15",
        "memo": "Purchase of supplies",
        "lines": [{"code": "6000", "name": "Supplies", "debit": 1200.0, "credit": 0}],
    },
    {
        "id": "33333333-3333-3333-3333-333333333333",
        "entry_date": "2025-02-10",
        "memo": "Sales to customer",
        "lines": [{"code": "4000", "name": "Revenue", "debit": 0, "credit": 5000.0}],
    },
]


# ---------------------------------------------------------------------------
# A5: tax summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tax_summary_parses_valid_categories() -> None:
    llm = _router(
        _completion(
            '{"categories": ['
            '{"category": "purchases", "detail": "tax on purchases", '
            '"input_tax": 100.0, "output_tax": 0, "net": -100.0}, '
            '{"category": "sales", "detail": "tax on sales", '
            '"input_tax": 0, "output_tax": 250.0, "net": 250.0}], '
            '"total_input": 100.0, "total_output": 250.0}'
        )
    )
    result = await generate_tax_summary(llm, period=_PERIOD, entries=_ENTRIES)
    assert result is not None
    assert [c.category for c in result.categories] == ["purchases", "sales"]
    assert result.total_input == 100.0
    assert result.total_output == 250.0
    assert result.model_used == "test-model"


@pytest.mark.asyncio
async def test_tax_summary_computes_net_when_missing() -> None:
    llm = _router(
        _completion(
            '{"categories": [{"category": "sales", "detail": "", '
            '"input_tax": 0, "output_tax": 50.0}]}'
        )
    )
    result = await generate_tax_summary(llm, period=_PERIOD, entries=_ENTRIES)
    assert result is not None
    assert result.categories[0].net == 50.0


@pytest.mark.asyncio
async def test_tax_summary_rejects_negative_amounts() -> None:
    llm = _router(
        _completion(
            '{"categories": [{"category": "purchases", "detail": "", '
            '"input_tax": -5.0, "output_tax": 0}]}'
        )
    )
    result = await generate_tax_summary(llm, period=_PERIOD, entries=_ENTRIES)
    assert result is None


@pytest.mark.asyncio
async def test_tax_summary_abstains_without_entries() -> None:
    result = await generate_tax_summary(_router(_completion("{}")), period=_PERIOD, entries=[])
    assert result is None


@pytest.mark.asyncio
async def test_tax_summary_abstains_on_unparseable() -> None:
    result = await generate_tax_summary(
        _router(_completion("no json here")), period=_PERIOD, entries=_ENTRIES
    )
    assert result is None


@pytest.mark.asyncio
async def test_tax_summary_uses_corrected_json_after_self_correction() -> None:
    draft = json.dumps(
        {
            "categories": [
                {
                    "category": "purchases",
                    "detail": "draft",
                    "input_tax": 4080,
                    "output_tax": 0,
                    "net": 4080,
                }
            ],
            "total_input": 4080,
            "total_output": 0,
        }
    )
    corrected = json.dumps(
        {
            "categories": [
                {
                    "category": "purchases",
                    "detail": "tax on purchases",
                    "input_tax": 4080,
                    "output_tax": 0,
                    "net": 4080,
                },
                {
                    "category": "sales",
                    "detail": "tax on sales",
                    "input_tax": 0,
                    "output_tax": 8160,
                    "net": 8160,
                },
            ],
            "total_input": 4080,
            "total_output": 8160,
        }
    )
    # llama-class LLMs occasionally emit a draft then a corrected object
    # ("...became..."); the final object must win, not the greedy span.
    completion = _completion(f"```json\n{draft}\n```\nbecame\n\n```json\n{corrected}\n```")
    result = await generate_tax_summary(_router(completion), period=_PERIOD, entries=_ENTRIES)
    assert result is not None
    assert [c.category for c in result.categories] == ["purchases", "sales"]
    assert result.total_input == 4080.0
    assert result.total_output == 8160.0


@pytest.mark.asyncio
async def test_tax_summary_abstains_on_llm_failure() -> None:
    router = MagicMock()
    router.complete = AsyncMock(side_effect=Exception("provider down"))
    result = await generate_tax_summary(router, period=_PERIOD, entries=_ENTRIES)
    assert result is None


# ---------------------------------------------------------------------------
# A10: audit narration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_narration_parses_valid_payload() -> None:
    llm = _router(
        _completion(
            '{"narration": "The period shows steady sales with one large '
            'disbursement.", '
            '"risk_areas": [{"risk_type": "unusual_high_value", '
            '"description": "A single 5000 sale dominates.", '
            '"severity": "high", "entry_id": "33333333-3333-3333-3333-333333333333"}]}'
        )
    )
    result = await narrate_audit(
        llm, from_date="2025-01-01", to_date="2025-03-31", entries=_ENTRIES
    )
    assert result is not None
    assert "steady sales" in result.narration
    assert len(result.risk_areas) == 1
    assert result.risk_areas[0].risk_type == "unusual_high_value"
    assert result.risk_areas[0].severity == "high"
    assert result.risk_areas[0].entry_id == _ENTRIES[1]["id"]


@pytest.mark.asyncio
async def test_audit_narration_drops_unknown_entry_id_and_invalid_severity() -> None:
    llm = _router(
        _completion(
            '{"narration": "ok narration.", '
            '"risk_areas": [{"risk_type": "round_trip", "description": "x", '
            '"severity": "critical", "entry_id": "99999999-9999-9999-9999-999999999999"}]}'
        )
    )
    result = await narrate_audit(
        llm, from_date="2025-01-01", to_date="2025-03-31", entries=_ENTRIES
    )
    assert result is not None
    assert result.risk_areas[0].entry_id is None
    assert result.risk_areas[0].severity == "medium"


@pytest.mark.asyncio
async def test_audit_narration_abstains_without_narration() -> None:
    llm = _router(_completion('{"narration": "", "risk_areas": []}'))
    result = await narrate_audit(
        llm, from_date="2025-01-01", to_date="2025-03-31", entries=_ENTRIES
    )
    assert result is None


# ---------------------------------------------------------------------------
# A12: document Q&A
# ---------------------------------------------------------------------------

_EVIDENCE = [
    {"source_ref": "doc/ar/policy", "chunk_text": "Net terms are 30 days.", "score": 0.85},
    {"source_ref": "doc/pnl/q1", "chunk_text": "Revenue was 5000.", "score": 0.7},
]


@pytest.mark.asyncio
async def test_qa_parses_valid_answer_with_citations() -> None:
    llm = _router(
        _completion(
            '{"answer": "Net terms are 30 days.", "citations": [{"source_ref": "doc/ar/policy"}]}'
        )
    )
    result = await answer_question(llm, question="What are net terms?", evidence=_EVIDENCE)
    assert result is not None
    assert result.answer == "Net terms are 30 days."
    assert len(result.citations) == 1
    assert result.citations[0].source_ref == "doc/ar/policy"
    assert result.citations[0].chunk_text == "Net terms are 30 days."
    assert result.citations[0].score == 0.85


@pytest.mark.asyncio
async def test_qa_drops_fabricated_citations() -> None:
    llm = _router(
        _completion(
            '{"answer": "According to a secret document.", '
            '"citations": [{"source_ref": "doc/not/provided"}]}'
        )
    )
    result = await answer_question(llm, question="Any secret?", evidence=_EVIDENCE)
    assert result is not None
    assert result.citations == ()


@pytest.mark.asyncio
async def test_qa_abstains_without_evidence() -> None:
    result = await answer_question(_router(_completion("{}")), question="Any?", evidence=[])
    assert result is None


@pytest.mark.asyncio
async def test_qa_abstains_on_missing_answer() -> None:
    llm = _router(_completion('{"answer": "", "citations": []}'))
    result = await answer_question(llm, question="Any?", evidence=_EVIDENCE)
    assert result is None
