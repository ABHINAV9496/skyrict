"""The (only) LLM touch point for the finance-docs suite (FIN-AI-004).

Three stateless LLM interactions, all abstention-first: any unusable outcome
(provider failure, invalid JSON, missing fields, empty/unbalanced data) maps to
``None`` - never a hard error - exactly like ``account_suggest``.

- ``generate_tax_summary`` (A5):  per-category input/output tax over a fiscal
  period's posted entries.
- ``narrate_audit`` (A10):        plain-English change narrative + risk areas
  over posted entries in a date range.
- ``answer_question`` (A12):      grounded Q&A over RAG-retrieved chunks; the
  model may ONLY cite source refs it was given, and citations are validated
  against that set before anything is returned.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import structlog

from ai_agent.core.providers import LlmRequest

if TYPE_CHECKING:
    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.finance_docs.schemas import (
        AuditNarration,
        DocAnswer,
        QaCitation,
        RiskArea,
        TaxCategory,
        TaxSummary,
    )

logger = structlog.get_logger("ai_agent.finance_docs")

# Guard against pathological snapshots blowing the provider context window.
# Aggregation lives in core; this is a prompt-size ceiling, not a data cutoff.
_MAX_ENTRIES_IN_PROMPT = 1500

_TAX_SYSTEM_PROMPT = (
    "You are a tax accountant producing a per-category input/output tax "
    "summary for a fiscal period, from its POSTED journal entries. "
    "Return ONLY strict JSON with the keys: "
    '"categories" (array of objects, each with "category" (the tax category '
    'name, e.g. "purchases", "sales", "expenses"), "detail" (one-sentence '
    'explanation of what the amounts cover), "input_tax" (tax paid on '
    'purchases, number >= 0), "output_tax" (tax charged on sales, number >= 0), '
    '"net" (number, equal to output_tax - input_tax)), '
    '"total_input" (sum of all input_tax), "total_output" (sum of all '
    'output_tax), "model_used" (your own model identifier) and "confidence" '
    "(0 to 1). If there is nothing taxable, categories must be an empty array. "
    "Amounts must be plain numbers, never strings."
)

_AUDIT_SYSTEM_PROMPT = (
    "You are a financial auditor reviewing posted journal entries. "
    "Return ONLY strict JSON with keys: "
    '"narration" (a 2-4 sentence plain-English summary of the period\'s '
    "transactions, quoting the most material figures), "
    '"risk_areas" (array of objects, each with "risk_type" (e.g. '
    '"round_trip", "unbalanced_batch", "unusual_high_value", '
    '"missing_source_ref"), "description" (what specifically looks risky and '
    'which entries), "severity" ("low", "medium" or "high"), and "entry_id" '
    "(the matching entry id from the provided list, or omit if none) - empty "
    'array if no risks) and "confidence" (0 to 1).'
)

_QA_SYSTEM_PROMPT = (
    "You are a financial assistant answering questions about a company's "
    "finance documents, using ONLY the provided evidence chunks. "
    'Return ONLY strict JSON with keys: "answer" (a direct, plain-English '
    "answer grounded exclusively in the provided chunks; if the chunks do not "
    'cover the question, answer "I could not find this in the documents."), '
    '"citations" (array of objects, each with "source_ref" - MUST be one of '
    "the source_refs provided in the evidence - avoided if unused) and "
    '"confidence" (0 to 1). Do not invent sources or figures.'
)


async def generate_tax_summary(
    llm_router: LlmRouter,
    *,
    period: dict[str, Any] | None,
    entries: list[dict[str, Any]],
) -> TaxSummary | None:
    """Generate per-category tax lines for a fiscal period; ``None`` on abstention."""
    from ai_agent.features.finance_docs.schemas import TaxCategory, TaxSummary

    if not entries:
        logger.info("finance_docs.tax_summary.no_entries")
        return None

    period_text = json.dumps(period or {}, ensure_ascii=False)
    entries_text = json.dumps(entries[:_MAX_ENTRIES_IN_PROMPT], ensure_ascii=False, default=str)
    user_prompt = f"Period:\n{period_text}\n\nPosted entries:\n{entries_text}"
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_TAX_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=800,
                temperature=0.0,
            )
        )
    except Exception:
        logger.warning("finance_docs.tax_summary.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        logger.warning("finance_docs.tax_summary.unparseable")
        return None

    raw_categories = payload.get("categories")
    if not isinstance(raw_categories, list) or not raw_categories:
        logger.warning("finance_docs.tax_summary.no_categories")
        return None

    categories: list[TaxCategory] = []
    for raw in raw_categories:
        if not isinstance(raw, dict):
            continue
        category = str(raw.get("category") or "").strip()
        if not category:
            continue
        input_tax = _as_nonnegative_number(raw.get("input_tax"))
        output_tax = _as_nonnegative_number(raw.get("output_tax"))
        if input_tax is None or output_tax is None:
            continue
        net = _as_number(raw.get("net"))
        if net is None:
            net = output_tax - input_tax
        categories.append(
            TaxCategory(
                category=category,
                detail=str(raw.get("detail") or "").strip(),
                input_tax=input_tax,
                output_tax=output_tax,
                net=net,
            )
        )

    if not categories:
        logger.warning("finance_docs.tax_summary.no_valid_categories")
        return None

    return TaxSummary(
        categories=tuple(categories),
        total_input=round(sum(c.input_tax for c in categories), 2),
        total_output=round(sum(c.output_tax for c in categories), 2),
        model_used=completion.model_used,
    )


async def narrate_audit(
    llm_router: LlmRouter,
    *,
    from_date: str,
    to_date: str,
    entries: list[dict[str, Any]],
) -> AuditNarration | None:
    """Narration + risk areas over posted entries; ``None`` on abstention."""
    from ai_agent.features.finance_docs.schemas import AuditNarration, RiskArea

    if not entries:
        logger.info("finance_docs.audit.no_entries")
        return None

    entry_ids = {str(e.get("id")) for e in entries}
    entries_text = json.dumps(entries[:_MAX_ENTRIES_IN_PROMPT], ensure_ascii=False, default=str)
    user_prompt = f"From: {from_date}\nTo: {to_date}\n\nPosted entries:\n{entries_text}"
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_AUDIT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=600,
                temperature=0.2,
            )
        )
    except Exception:
        logger.warning("finance_docs.audit.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        logger.warning("finance_docs.audit.unparseable")
        return None

    narration = str(payload.get("narration") or "").strip()
    if not narration:
        logger.warning("finance_docs.audit.no_narration")
        return None

    risk_areas: list[RiskArea] = []
    for raw in cast("list[Any]", payload.get("risk_areas") or []):
        if not isinstance(raw, dict):
            continue
        risk_type = str(raw.get("risk_type") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not risk_type or not description:
            continue
        entry_id = str(raw.get("entry_id") or "").strip() or None
        if entry_id is not None and entry_id not in entry_ids:
            entry_id = None
        severity = str(raw.get("severity") or "medium").strip().lower()
        if severity not in ("low", "medium", "high"):
            severity = "medium"
        risk_areas.append(
            RiskArea(
                entry_id=entry_id,
                risk_type=risk_type,
                description=description,
                severity=severity,
            )
        )

    return AuditNarration(
        narration=narration,
        risk_areas=tuple(risk_areas),
        model_used=completion.model_used,
    )


async def answer_question(
    llm_router: LlmRouter,
    *,
    question: str,
    evidence: list[dict[str, Any]],
) -> DocAnswer | None:
    """Grounded answer over RAG evidence; citations validated against source_refs."""
    from ai_agent.features.finance_docs.schemas import DocAnswer, QaCitation

    if not evidence:
        logger.info("finance_docs.qa.no_evidence")
        return None

    evidence_text = json.dumps(evidence, ensure_ascii=False, default=str)
    user_prompt = f"Question: {question}\n\nEvidence:\n{evidence_text}"
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_QA_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=500,
                temperature=0.1,
            )
        )
    except Exception:
        logger.warning("finance_docs.qa.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        logger.warning("finance_docs.qa.unparseable")
        return None

    answer = str(payload.get("answer") or "").strip()
    if not answer:
        logger.warning("finance_docs.qa.no_answer")
        return None

    by_ref = {str(e.get("source_ref")): e for e in evidence}
    citations: list[QaCitation] = []
    for raw in cast("list[Any]", payload.get("citations") or []):
        if not isinstance(raw, dict):
            continue
        source_ref = str(raw.get("source_ref") or "").strip()
        source = by_ref.get(source_ref)
        if source is None:
            continue
        citations.append(
            QaCitation(
                source_ref=source_ref,
                chunk_text=str(source.get("chunk_text") or "").strip(),
                score=_as_number(source.get("score")) or 0.0,
            )
        )

    return DocAnswer(
        answer=answer,
        citations=tuple(citations),
        model_used=completion.model_used,
    )


def _parse_json(text: str) -> dict[str, object] | None:
    """Parse the model's JSON, tolerating fences and self-correction.

    A single top-level object (outer object, even with nested line/risk
    arrays) wins outright. When a model drafts then re-emits ("...became..."),
    returns the **last** top-level object: the corrected final answer.
    """
    decoder = json.JSONDecoder()
    candidates: list[tuple[int, int, dict[str, object]]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, end = decoder.raw_decode(text[index:])
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            candidates.append((index, index + end, obj))

    top_level = [
        (start, end, obj)
        for (start, end, obj) in candidates
        if not any(s < start and e > end for (s, e, _) in candidates)
    ]
    if not top_level:
        return None
    return top_level[-1][2]


def _as_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_nonnegative_number(value: object) -> float | None:
    number = _as_number(value)
    if number is None or number < 0:
        return None
    return number
