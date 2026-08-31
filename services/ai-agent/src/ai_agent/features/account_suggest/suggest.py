"""The (only) LLM touch point for account-code suggestions.

Turns a description + chart-of-accounts into a single best account. The LLM
may ONLY pick from the provided list — it is told the code must equal one of
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
    "chart of accounts (list of {code, name}), choose the SINGLE best account "
    "for the transaction. The suggested_code MUST be one of the codes provided "
    "in the chart — never invent a code. If no account fits, return "
    "suggested_code as an empty string. Return ONLY strict JSON with the keys: "
    '"suggested_code" (string), "suggested_name" (string), "confidence" '
    "(a number 0 to 1 reflecting how confidently the account fits), and "
    '"reasoning" (a short one-sentence, plain-English explanation of why this '
    "account fits the transaction)."
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

    from ai_agent.features.account_suggest.schemas import AccountSuggestion

    return AccountSuggestion(
        suggested_code=code,
        suggested_name=name,
        confidence=max(0.0, min(float(confidence), 1.0)),
        reasoning=reasoning,
        model_used=completion.model_used,
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
