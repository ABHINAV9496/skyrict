"""Unit tests for the RAGAS eval runner's pure logic (SKY-58).

The ragas import is deliberately lazy (the nightly workflow installs it
ephemerally), so everything testable without it — sample mapping, mean
aggregation, threshold gating, Decimal coercion — lives here and is exercised
by regular CI.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from ai_agent.features.rag.retrieval.service import RetrievalItem, RetrievalResult
from ai_agent.rag_eval import (
    _build_samples,
    _eval_user_id,
    _gates_passed,
    _select_cases,
    _summarize_samples,
    _to_decimal,
)
from ai_agent.rag_eval_cases import RagEvalCase

_TENANT_ID = uuid.uuid4()


def _result(*texts: str, cached: bool = False) -> RetrievalResult:
    items = [
        RetrievalItem(
            parent_id=uuid.uuid4(),
            source_ref=f"docs/{index}",
            module="docs",
            chunk_text=text,
            score=0.9 - index / 100,
            child_hits=1,
            metadata_={},
        )
        for index, text in enumerate(texts)
    ]
    return RetrievalResult(
        data=items,
        model_used=None if cached else "fake-model",
        latency_ms=0,
        cached=cached,
        query_hash="a" * 64,
    )


class TestSelectCases:
    def test_returns_all_cases_when_module_is_none(self) -> None:
        from ai_agent.rag_eval_cases import RAG_EVAL_CASES

        assert _select_cases(None) == list(RAG_EVAL_CASES)

    def test_filters_by_module(self) -> None:
        cases = _select_cases("products")
        assert cases
        assert all(case.module == "products" for case in cases)

    def test_unknown_module_raises(self) -> None:
        with pytest.raises(Exception, match="no eval cases"):
            _select_cases("hr")


class TestBuildSamples:
    def test_maps_ragas_contract_keys(self) -> None:
        case = RagEvalCase(
            question="What is a child chunk?", answer="A ~400-token block.", module="docs"
        )
        result = _result("Child chunks are embedded.", "Parents are not embedded.")
        samples = _build_samples([(case, result, "A chunk is embedded.")])

        assert len(samples) == 1
        sample = samples[0]
        assert sample["user_input"] == case.question
        assert sample["reference"] == case.answer
        assert sample["response"] == "A chunk is embedded."
        assert sample["retrieved_contexts"] == [
            "Child chunks are embedded.",
            "Parents are not embedded.",
        ]


class TestSummarizeSamples:
    def test_means_numeric_metrics(self) -> None:
        samples = [
            {"faithfulness": 0.8, "answer_relevancy": 0.6},
            {"faithfulness": 1.0, "answer_relevancy": 0.8},
        ]
        assert _summarize_samples(samples) == {
            "faithfulness": 0.9,
            "answer_relevancy": 0.7,
        }

    def test_drops_non_numeric_values(self) -> None:
        samples = [{"faithfulness": 0.9, "note": "ok"}]
        assert _summarize_samples(samples) == {"faithfulness": 0.9}

    def test_empty_input(self) -> None:
        assert _summarize_samples([]) == {}


class TestGatesPassed:
    def test_pass_when_every_metric_meets_threshold(self) -> None:
        passed, failures = _gates_passed(
            {"faithfulness": 0.85, "answer_relevancy": 0.75}, {"faithfulness": 0.8}
        )
        assert passed
        assert failures == ()

    def test_fail_with_all_breaches_listed(self) -> None:
        passed, failures = _gates_passed(
            {"faithfulness": 0.7, "answer_relevancy": 0.9},
            {"faithfulness": 0.8, "answer_relevancy": 0.85},
        )
        assert not passed
        assert failures == ("faithfulness",)

    def test_missing_metric_counts_as_zero(self) -> None:
        passed, failures = _gates_passed({}, {"faithfulness": 0.8})
        assert not passed
        assert failures == ("faithfulness",)


class TestToDecimal:
    def test_rounds_and_clamps(self) -> None:
        assert _to_decimal(0.87654) == Decimal("0.8765")
        assert _to_decimal(1.5) == Decimal("1.0000")
        assert _to_decimal(-0.1) == Decimal("0.0000")

    def test_none_stays_none(self) -> None:
        assert _to_decimal(None) is None


class TestEvalUserId:
    def test_is_deterministic_and_tenant_scoped(self) -> None:
        first = _eval_user_id(_TENANT_ID)
        assert first == _eval_user_id(_TENANT_ID)
        assert first != _eval_user_id(uuid.uuid4())
