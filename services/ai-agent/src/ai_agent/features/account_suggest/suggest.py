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
    from ai_agent.features.account_suggest.schemas import AccountSuggestion, SuggestRequest

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
