"""The (only) LLM touch point for account-code suggestions.

Turns a description + chart-of-accounts into a single best account. The LLM
may ONLY pick from the provided list - it is told the code must equal one of
the codes it was given, so a fabricated or out-of-chart account is rejected.
Unusable LLM output (invalid JSON, missing fields, out-of-list code, provider
failure) maps to ``None`` (an abstention), never a hard error.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.providers import LlmRequest

if TYPE_CHECKING:
    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.account_suggest.schemas import (
        AccountSuggestion,
        DraftSuggestion,
        SuggestRequest,
    )

logger = structlog.get_logger("ai_agent.account_suggest")

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM_PROMPT = (
    "You are a bookkeeping assistant. Given a transaction description and a "
    "chart of accounts (list of {code, name}), choose the BEST pair of "
    "accounts for a double-entry journal entry: one debit and one credit. "
    "Both codes MUST be from the provided chart - never invent codes. "
    "Also extract the transaction amount if mentioned (as a positive number, "
    "or null if not stated). Return ONLY strict JSON with the keys: "
    '"suggested_code" (the debit account code), "suggested_name" (the debit '
    'account name), "contra_code" (the credit account code), "contra_name" '
    '(the credit account name), "confidence" (a number 0 to 1), "reasoning" '
    '(a short one-sentence explanation), "amount" (number or null), and '
    '"side" ("debit" or "credit").'
)

_DRAFT_SYSTEM_PROMPT = (
    "You are a bookkeeping assistant. Given a transaction description and a "
    "chart of accounts (list of {code, name}), create a complete double-entry "
    "journal entry with ALL required lines. "
    "All account codes MUST be from the provided chart — never invent codes. "
    "Return ONLY strict JSON with the keys: "
    '"lines" (array of objects, each with "account_code", "account_name", '
    '"amount" (positive number), "side" ("debit" or "credit"), "description"), '
    '"explanation" (explain the account relationships and why each line is '
    'needed), "confidence" (a number 0 to 1, set below 0.75 if uncertain), '
    '"reasoning" (step-by-step thought process). '
    "Rules: total debits MUST equal total credits. Every line must have a "
    "valid account code from the chart. Amounts must be positive numbers."
)

_NARRATE_SYSTEM_PROMPT = (
    "You are a financial analyst. Explain this anomaly in plain English. "
    "Cite the specific figures that triggered it. Reference what this type "
    "of anomaly typically means. Suggest resolution steps. "
    "Return ONLY strict JSON with keys: "
    '"narration" (string, 2-4 sentences), '
    '"confidence" (number 0 to 1).'
)

_REMINDER_SYSTEM_PROMPT = (
    "You are a professional accounts receivable assistant. Draft a payment "
    "reminder email for an overdue invoice. Use the tone specified. "
    "Return ONLY strict JSON with keys: "
    '"subject" (email subject line), '
    '"body" (the email body, plain text, 3-5 sentences), '
    '"tone" (the tone used).'
)


async def suggest(llm_router: LlmRouter, req: SuggestRequest) -> AccountSuggestion | None:
    """Generate an account-code suggestion; return ``None`` on any unusable outcome."""
    codes = {a.code for a in req.accounts}
    chart_json = json.dumps(
        [{"code": a.code, "name": a.name} for a in req.accounts],
        ensure_ascii=False,
    )
    user_prompt = f"Description: {req.description}\n\nChart of accounts:\n{chart_json}"
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.0,
            )
        )
    except Exception:
        logger.warning("account_suggest.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        logger.warning("account_suggest.unparseable")
        return None

    code = str(payload.get("suggested_code") or "").strip()
    name = str(payload.get("suggested_name") or "").strip()
    if not name or code not in codes:
        logger.warning("account_suggest.out_of_chart_or_blank", code=code[:64])
        return None

    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        logger.warning("account_suggest.bad_confidence")
        return None

    reasoning = str(payload.get("reasoning") or "").strip()

    raw_amount = payload.get("amount")
    amount: float | None = None
    if isinstance(raw_amount, (int, float)) and raw_amount > 0:
        amount = float(raw_amount)

    raw_side = str(payload.get("side") or "debit").strip().lower()
    side = raw_side if raw_side in ("debit", "credit") else "debit"

    contra_code = str(payload.get("contra_code") or "").strip()
    contra_name = str(payload.get("contra_name") or "").strip()
    if contra_code and contra_code not in codes:
        contra_code = ""
        contra_name = ""

    from ai_agent.features.account_suggest.schemas import AccountSuggestion

    return AccountSuggestion(
        suggested_code=code,
        suggested_name=name,
        confidence=max(0.0, min(float(confidence), 1.0)),
        reasoning=reasoning,
        model_used=completion.model_used,
        amount=amount,
        side=side,
        contra_code=contra_code,
        contra_name=contra_name,
    )


async def draft_entry(llm_router: LlmRouter, req: SuggestRequest) -> DraftSuggestion | None:
    """Generate a multi-line journal entry draft; return ``None`` on failure."""
    chart_json = json.dumps(
        [{"code": a.code, "name": a.name} for a in req.accounts],
        ensure_ascii=False,
    )
    user_prompt = f"Description: {req.description}\n\nChart of accounts:\n{chart_json}"
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_DRAFT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=600,
                temperature=0.0,
            )
        )
    except Exception:
        logger.warning("draft_entry.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        logger.warning("draft_entry.unparseable")
        return None

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        logger.warning("draft_entry.no_lines")
        return None

    codes = {a.code for a in req.accounts}
    from ai_agent.features.account_suggest.schemas import DraftSuggestion, JournalLineSuggestion

    lines: list[JournalLineSuggestion] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("account_code") or "").strip()
        if code not in codes:
            logger.warning("draft_entry.out_of_chart", code=code[:64])
            continue
        amt = raw.get("amount")
        if not isinstance(amt, (int, float)) or amt <= 0:
            continue
        side_val = str(raw.get("side") or "debit").strip().lower()
        if side_val not in ("debit", "credit"):
            side_val = "debit"
        name_str = str(raw.get("account_name") or "").strip()
        if not name_str:
            # look up name from chart
            for a in req.accounts:
                if a.code == code:
                    name_str = a.name
                    break
        lines.append(
            JournalLineSuggestion(
                account_code=code,
                account_name=name_str,
                amount=float(amt),
                side=side_val,
                description=str(raw.get("description") or "").strip(),
            )
        )

    if not lines:
        logger.warning("draft_entry.no_valid_lines")
        return None

    total_debit = sum(line.amount for line in lines if line.side == "debit")
    total_credit = sum(line.amount for line in lines if line.side == "credit")
    if abs(total_debit - total_credit) > 0.01:
        logger.warning("draft_entry.unbalanced", debit=total_debit, credit=total_credit)
        # still return but lower confidence

    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(float(confidence), 1.0))

    return DraftSuggestion(
        lines=tuple(lines),
        explanation=str(payload.get("explanation") or "").strip(),
        confidence=confidence,
        reasoning=str(payload.get("reasoning") or "").strip(),
        model_used=completion.model_used,
    )


async def narrate_anomaly(
    llm_router: LlmRouter, *, anomaly_type: str, description: str, severity: str
) -> dict[str, str] | None:
    """Generate a plain-English narration of a finance anomaly."""
    user_prompt = f"Anomaly type: {anomaly_type}\nSeverity: {severity}\nDescription: {description}"
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_NARRATE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=300,
                temperature=0.2,
            )
        )
    except Exception:
        logger.warning("narrate_anomaly.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        return None

    narration = str(payload.get("narration") or "").strip()
    if not narration:
        return None

    return {"narration": narration, "model_used": completion.model_used}


async def draft_reminder(
    llm_router: LlmRouter,
    *,
    customer_name: str | None,
    invoice_number: str,
    amount: float,
    days_overdue: int,
    tone: str,
) -> dict[str, str] | None:
    """Draft a payment reminder email."""
    user_prompt = (
        f"Customer: {customer_name or 'Valued Customer'}\n"
        f"Invoice: {invoice_number}\n"
        f"Amount due: {amount:.2f}\n"
        f"Days overdue: {days_overdue}\n"
        f"Requested tone: {tone}"
    )
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_REMINDER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=400,
                temperature=0.3,
            )
        )
    except Exception:
        logger.warning("draft_reminder.llm_failed")
        return None

    payload = _parse_json(completion.text)
    if payload is None:
        return None

    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not subject or not body:
        return None

    return {
        "subject": subject,
        "body": body,
        "tone": tone,
        "model_used": completion.model_used,
    }


def _parse_json(text: str) -> dict[str, object] | None:
    """Strip markdown fences/cruft and parse the first JSON object."""
    match = _JSON_OBJECT_RE.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None
