"""Unit tests for the finance prompt-eval harness FIN-AI-004 features.

Runs the real ``run_registry`` dispatch (a5_tax_summary / a10_audit /
a12_doc_qa) over a temp registry with a fake LLM router keyed on the
production system prompts, and asserts the deterministic scoring rules.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from ai_agent.features.finance_eval.harness import run_registry


def _completion(text: str) -> MagicMock:
    completion = MagicMock()
    completion.text = text
    completion.model_used = "test-model"
    return completion


def _router() -> MagicMock:
    async def complete(request) -> MagicMock:
        system = request.system_prompt
        if "tax accountant" in system:
            return _completion(
                '{"categories": [{"category": "sales", "detail": "tax on '
                'sales", "input_tax": 0, "output_tax": 250.0, "net": 250.0}], '
                '"total_input": 0, "total_output": 250.0}'
            )
        if "financial auditor" in system:
            return _completion('{"narration": "Sales reached $5,000 in Q1.", "risk_areas": []}')
        if "payment terms" in request.user_prompt:
            return _completion(
                '{"answer": "Payment is due net 30.", "citations": [{"source_ref": '
                '"INV-2026-00042-chunk-0"}]}'
            )
        return _completion('{"answer": "I could not find this in the documents.", "citations": []}')

    router = MagicMock()
    router.complete = AsyncMock(side_effect=complete)
    return router


def _registry(tmp_path) -> str:
    data = {
        "threshold": 0.5,
        "prompt_id": "test",
        "features": [
            {
                "name": "a5_tax_summary",
                "cases": [
                    {
                        "id": "a5-ok",
                        "period": {"name": "FY 2026-Q1"},
                        "entries": [{"id": "e1", "memo": "sale", "lines": []}],
                        "expected_category": "sales",
                    },
                    {
                        "id": "a5-wrong",
                        "period": {"name": "FY 2026-Q1"},
                        "entries": [{"id": "e2", "memo": "sale", "lines": []}],
                        "expected_category": "purchases",
                    },
                    {
                        "id": "a5-abstain",
                        "period": {"name": "FY 2026-Q1"},
                        "entries": [],
                        "expect_abstain": True,
                    },
                ],
            },
            {
                "name": "a10_audit",
                "cases": [
                    {
                        "id": "a10-ok",
                        "from_date": "2026-01-01",
                        "to_date": "2026-03-31",
                        "entries": [{"id": "e1", "memo": "sale", "lines": []}],
                        "expected_cites_figure": True,
                    }
                ],
            },
            {
                "name": "a12_doc_qa",
                "cases": [
                    {
                        "id": "a12-cite",
                        "question": "What are the payment terms on invoice INV-2026-00042?",
                        "evidence": [
                            {
                                "source_ref": "INV-2026-00042-chunk-0",
                                "chunk_text": "net 30",
                                "score": 0.9,
                            }
                        ],
                        "expected_citations": True,
                    },
                    {
                        "id": "a12-nocite",
                        "question": "How many vacation days do employees get?",
                        "evidence": [
                            {
                                "source_ref": "INV-2026-00042-chunk-0",
                                "chunk_text": "net 30",
                                "score": 0.9,
                            }
                        ],
                        "expected_citations": False,
                    },
                    {
                        "id": "a12-abstain",
                        "question": "What is the total balance?",
                        "evidence": [],
                        "expect_abstain": True,
                    },
                ],
            },
        ],
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


@pytest.mark.asyncio
async def test_finance_docs_eval_features(tmp_path) -> None:
    metrics = await run_registry(_registry(tmp_path), _router())
    by_feature = {metric.feature: metric for metric in metrics}

    tax = by_feature["a5_tax_summary"]
    assert tax.considered == 3
    assert tax.abstained == 0
    assert tax.precision == 2 / 3
    assert tax.details == {"a5-ok": "correct", "a5-wrong": "incorrect", "a5-abstain": "correct"}
    assert tax.met_threshold is True

    audit = by_feature["a10_audit"]
    assert audit.considered == 1
    assert audit.precision == 1.0
    assert audit.details == {"a10-ok": "correct"}

    qa = by_feature["a12_doc_qa"]
    assert qa.considered == 3
    assert qa.precision == 1.0
    assert qa.details == {"a12-cite": "correct", "a12-nocite": "correct", "a12-abstain": "correct"}
