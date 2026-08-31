"""Unit tests for the ai-agent account-code suggester (SKY-56/SKY-64).

A fake LlmRouter: no network, no provider. Covers success, abstention on
invalid/unparseable output, out-of-chart code rejection, blank code, bad
confidence, and LLM failure.
"""

from __future__ import annotations

import pytest

from ai_agent.core.providers import LlmCompletion
from ai_agent.features.account_suggest.schemas import AccountOption, SuggestRequest
from ai_agent.features.account_suggest.suggest import _parse_json, suggest


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
    ' "confidence": 0.9, "reasoning": "Furniture is a fixed asset."}'
)


async def test_suggest_success() -> None:
    result = await suggest(FakeLlm(text=_GOOD), _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.suggested_code == "1500"
    assert result.suggested_name == "Equipment"
    assert result.confidence == pytest.approx(0.9)
    assert result.reasoning == "Furniture is a fixed asset."
    assert result.model_used == "fake-model"


async def test_suggest_reasoning_defaults_empty_when_absent() -> None:
    llm = FakeLlm(
        text='{"suggested_code": "1500", "suggested_name": "Equipment", "confidence": 0.9}'
    )
    result = await suggest(llm, _req())  # type: ignore[arg-type]
    assert result is not None
    assert result.reasoning == ""


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
