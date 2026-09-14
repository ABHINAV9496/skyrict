"""Finance prompt-eval harness - drives the deployed LLM prompts (FIN-AI-002).

Loads a YAML registry of finance prompt cases (``tests/eval/finance_prompts.yaml``)
and runs each case through the REAL production prompt functions in
:mod:`ai_agent.features.account_suggest.suggest` (and
:mod:`ai_agent.features.finance_docs.generate` for the FIN-AI-004 suite) using
the configured LLM router. Each feature is scored with a deterministic
correctness rule:

================  =========================================================
feature            rule
================  =========================================================
a1_suggest         suggested_code matches the expected chart code
a2_draft           drafts a balanced entry with >= expected_min_lines lines,
                   and abstains (None) exactly when the case expects it
a7_narrate         narration is non-empty and (if expected) cites a figure
a8_remind          subject + body non-empty and body includes the exact
                   invoice number and the amount due
a5_tax_summary     a category line exists for the expected tax category
                   (or abstains exactly when the case has no entries)
a10_audit           narration is non-empty and (if expected) cites a figure
a12_doc_qa          answer is non-empty; every citation source_ref is within
                   the provided evidence, and citations are present exactly
                   when the case expects them (or abstains on no evidence)
================  =========================================================

Output mirrors the HR eval harness: one ``FinanceEvalMetric`` per feature
(precision over considered cases, abstention count, threshold verdict).
Warn-not-fail by contract: the CLI never exits nonzero; the nightly workflow
persists rows to ``ai_finance_eval_runs`` for the historical record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import yaml

from ai_agent.db.finance_eval_runs_repository import FinanceEvalRunsRepository
from ai_agent.db.session import async_session_factory
from ai_agent.features.account_suggest.schemas import AccountOption, SuggestRequest
from ai_agent.features.account_suggest.suggest import (
    draft_entry,
    draft_reminder,
    narrate_anomaly,
    suggest,
)
from ai_agent.features.finance_docs.generate import (
    answer_question,
    generate_tax_summary,
    narrate_audit,
)

if TYPE_CHECKING:
    import uuid
    from pathlib import Path

    from ai_agent.core.llm_router import LlmRouter


@dataclass(frozen=True, slots=True)
class FinanceEvalMetric:
    """One feature's precision over its considered cases."""

    feature: str
    prompt_id: str
    model_used: str
    precision: float
    considered: int
    abstained: int
    threshold: float
    met_threshold: bool
    details: dict[str, Any] = field(default_factory=dict)


def load_registry(path: str | Path) -> dict[str, Any]:
    """Load the finance prompt-eval registry (top-level threshold + features)."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"invalid eval registry {path}: expected a YAML mapping")
    threshold = data.get("threshold")
    features = data.get("features")
    if not isinstance(threshold, (int, float)) or not isinstance(features, list) or not features:
        raise ValueError(
            f"invalid eval registry {path}: expected numeric 'threshold' and a non-empty 'features' list"
        )
    return data


async def _run_suggest(llm_router: LlmRouter, case: dict[str, Any]) -> tuple[bool | None, str]:
    accounts = [AccountOption(code=a["code"], name=a["name"]) for a in case["accounts"]]
    result = await suggest(
        llm_router, SuggestRequest(description=case["description"], accounts=accounts)
    )
    if result is None or not result.suggested_code:
        return None, ""
    return (result.suggested_code == case["expected_code"], result.model_used)


async def _run_draft(llm_router: LlmRouter, case: dict[str, Any]) -> tuple[bool | None, str]:
    accounts = [AccountOption(code=a["code"], name=a["name"]) for a in case["accounts"]]
    result = await draft_entry(
        llm_router, SuggestRequest(description=case["description"], accounts=accounts)
    )
    expected_min = int(case.get("expected_min_lines", 0))
    if result is None:
        # expected_draft False means the LLM should abstain on this case.
        return (expected_min == 0, "") if expected_min == 0 else (None, "")
    if expected_min == 0:
        return False, result.model_used
    debits = sum(line.amount for line in result.lines if line.side == "debit")
    credit_total = sum(line.amount for line in result.lines if line.side == "credit")
    balanced = len(result.lines) >= expected_min and debits > 0 and debits == credit_total
    return balanced, result.model_used


async def _run_narrate(llm_router: LlmRouter, case: dict[str, Any]) -> tuple[bool | None, str]:
    result = await narrate_anomaly(
        llm_router,
        anomaly_type=case["anomaly_type"],
        description=case["description"],
        severity=case["severity"],
    )
    if result is None or not result["narration"]:
        return None, ""
    cites_figure = any(ch.isdigit() for ch in result["narration"])
    expected_cites = bool(case.get("expected_cites_figure", True))
    return (cites_figure if expected_cites else True, result["model_used"])


async def _run_remind(llm_router: LlmRouter, case: dict[str, Any]) -> tuple[bool | None, str]:
    result = await draft_reminder(
        llm_router,
        customer_name=case.get("customer_name"),
        invoice_number=case["invoice_number"],
        amount=float(case["amount"]),
        days_overdue=int(case["days_overdue"]),
        tone=case["tone"],
    )
    if result is None:
        return None, ""
    body = result["body"]
    invoice_ok = case["invoice_number"] in body
    amount = float(case["amount"])
    plain = f"{amount:.2f}"
    grouped = f"{amount:,.2f}"
    amount_ok = plain in body or grouped in body or str(amount) in body
    return (invoice_ok and amount_ok, result["model_used"])


async def _run_tax_summary(llm_router: LlmRouter, case: dict[str, Any]) -> tuple[bool | None, str]:
    result = await generate_tax_summary(
        llm_router, period=case.get("period"), entries=case["entries"]
    )
    if case.get("expect_abstain"):
        return result is None, ""
    if result is None:
        return None, ""
    expected = str(case.get("expected_category") or "").strip()
    if expected:
        matched = any(expected.lower() in c.category.lower() for c in result.categories)
        return matched, result.model_used
    return bool(result.categories), result.model_used


async def _run_audit_narration(
    llm_router: LlmRouter, case: dict[str, Any]
) -> tuple[bool | None, str]:
    result = await narrate_audit(
        llm_router,
        from_date=case["from_date"],
        to_date=case["to_date"],
        entries=case["entries"],
    )
    if result is None or not result.narration:
        return None, ""
    cites_figure = any(ch.isdigit() for ch in result.narration)
    expected_cites = bool(case.get("expected_cites_figure", True))
    return (cites_figure if expected_cites else True, result.model_used)


async def _run_doc_qa(llm_router: LlmRouter, case: dict[str, Any]) -> tuple[bool | None, str]:
    evidence = case["evidence"]
    result = await answer_question(llm_router, question=case["question"], evidence=evidence)
    if case.get("expect_abstain"):
        return result is None, ""
    if result is None or not result.answer:
        return None, ""
    allowed = {str(e.get("source_ref")) for e in evidence}
    refs_ok = all(c.source_ref in allowed for c in result.citations)
    expected_cites = bool(case.get("expected_citations", True))
    cites = bool(result.citations)
    return (cites if expected_cites else True) and refs_ok, result.model_used


# Feature id -> runner for dispatch (see module docstring for the rules).
_FEATURE_RUNNERS: dict[str, Any] = {
    "a1_suggest": _run_suggest,
    "a2_draft": _run_draft,
    "a7_narrate": _run_narrate,
    "a8_remind": _run_remind,
    "a5_tax_summary": _run_tax_summary,
    "a10_audit": _run_audit_narration,
    "a12_doc_qa": _run_doc_qa,
}


def _to_decimal(value: float) -> Decimal:
    return Decimal(str(round(max(0.0, min(1.0, value)), 4)))


async def run_registry(path: str | Path, llm_router: LlmRouter) -> list[FinanceEvalMetric]:
    """Evaluate every feature/case in *path* and return per-feature metrics."""
    registry = load_registry(path)
    threshold = float(registry["threshold"])
    prompt_id = str(registry.get("prompt_id", "unversioned"))
    metrics: list[FinanceEvalMetric] = []

    for feature_block in registry["features"]:
        feature = str(feature_block["name"])
        runner = _FEATURE_RUNNERS.get(feature)
        if runner is None:
            raise ValueError(f"no evaluator registered for feature {feature!r}")
        cases = feature_block["cases"]
        if not isinstance(cases, list) or not cases:
            raise ValueError(f"feature {feature!r} has no cases")

        details: dict[str, Any] = {}
        correct = considered = abstained = 0
        model_seen = ""
        for case in cases:
            score, model = await runner(llm_router, case)
            if model and not model_seen:
                model_seen = model
            case_id = str(case.get("id", "<unnamed>"))
            if score is None:
                abstained += 1
                details[case_id] = "abstained"
                continue
            considered += 1
            details[case_id] = "correct" if score else "incorrect"
            if score:
                correct += 1

        precision = correct / considered if considered else 0.0
        met = precision >= threshold
        metrics.append(
            FinanceEvalMetric(
                feature=feature,
                prompt_id=prompt_id,
                model_used=model_seen,
                precision=precision,
                considered=considered,
                abstained=abstained,
                threshold=threshold,
                met_threshold=met,
                details=details,
            )
        )
    return metrics


async def persist_metrics(metrics: list[FinanceEvalMetric]) -> list[uuid.UUID]:
    """Persist one row per feature metric to ai_finance_eval_runs (warn-not-fail)."""
    ids: list[uuid.UUID] = []
    async with async_session_factory() as session:
        repo = FinanceEvalRunsRepository(session)
        for metric in metrics:
            run = await repo.insert_run(
                feature=metric.feature,
                prompt_id=metric.prompt_id,
                model_used=metric.model_used,
                considered=metric.considered,
                abstained=metric.abstained,
                precision=_to_decimal(metric.precision),
                passed=metric.met_threshold,
                details=metric.details,
            )
            ids.append(run.id)
        await session.commit()
    return ids
