"""CRM transcript analysis engine (SKY-91 Part 13).

The one CRM AI flow where the LLM is the product, not the summarizer of a
deterministic score: it reads a raw call/meeting transcript and produces the
structured interpretation surfaced in the deal-detail insights panel -
summary, objection score, objections, next-best action, sentiment, and key
topics.

SKY-91 principle: "LLMs interpret, deterministic logic is authoritative for
numbers". The only numbers that flow from the model go through deterministic
sanitization here: ``objection_score`` is clamped to 0..100, ``sentiment`` is
coerced to the allowed enum, lists are deduplicated + capped, and a response
that cannot produce a usable summary + score raises ``AiInvalidResponseError``
(502) instead of being persisted as a valid analysis next to the transcript.

PII: the transcript is sent with a ``json_mode`` request through
``LlmRouter.complete``, so the router's redaction gate masks sensitive values
BEFORE any provider serializes the payload (the same gate every outbound
provider call passes). The raw transcript itself is never stored in this
feature - it lives in core on ``erp_crm_activities.transcript_text``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ai_agent.core.exceptions import AiInvalidResponseError
from ai_agent.core.providers.base import LlmRequest

if TYPE_CHECKING:
    from ai_agent.core.llm_router import LlmRouter

# Version stamped on every analysis row (bump on prompt/schema drift).
TRANSCRIPT_ANALYSIS_VERSION = "v1"

# Sanitization bounds (deterministic authority over the model's output).
_MAX_KEY_TOPICS = 10
_MAX_OBJECTIONS = 8
_MAX_STRING_LEN = 2000
_MAX_ACTION_LEN = 500
_MAX_TRANSCRIPT_CHARS = 60_000

_SENTIMENT_VALUES = ("positive", "neutral", "negative", "mixed")

_SYSTEM_PROMPT = (
    "You analyze a raw sales call/meeting transcript and return STRICT JSON "
    'with exactly these keys: "summary" (string, 1-3 sentences, no marketing '
    'language), "objection_score" (integer 0-100; 0 = no objections, 100 = '
    'deal-killing resistance), "objections" (array of strings; each objection '
    'as a short verbatim-ish phrase), "next_best_action" (string or null; the '
    'single highest-leverage next step the seller should take), "sentiment" '
    '(one of "positive", "neutral", "negative", "mixed"), "key_topics" '
    '(array of strings; the 3-8 main topics discussed), "confidence" '
    "(float 0-1; how certain you are about this reading). "
    "Do not invent facts. If something is unclear, reflect that in confidence."
)

_PROMPT_TEMPLATE = (
    "Analyze the following call/meeting transcript and return the JSON object "
    "described in your instructions:\n\n{transcript}"
)


@dataclass(frozen=True, slots=True)
class TranscriptAnalysis:
    """A sanitized transcript interpretation, ready to persist/display."""

    summary: str
    objection_score: int
    objections: list[str] = field(default_factory=list)
    next_best_action: str | None = None
    sentiment: str = "neutral"
    key_topics: list[str] = field(default_factory=list)
    confidence: float = 0.0


async def analyze_transcript(*, transcript: str, llm: LlmRouter) -> TranscriptAnalysis:
    """Run one transcript through the LLM and return the sanitized analysis.

    Raises:
        AiInvalidResponseError: The transcript is empty or the model's output
            could not be parsed into a usable analysis (never persisted).
        AiUnavailableError: No eligible provider served the request.
    """
    if not _clean_text(transcript):
        raise AiInvalidResponseError("Transcript is empty")

    request = LlmRequest(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_PROMPT_TEMPLATE.format(transcript=transcript[:_MAX_TRANSCRIPT_CHARS]),
        max_tokens=700,
        temperature=0.2,
        json_mode=True,
    )
    completion = await llm.complete(request)
    return _parse_analysis(completion.text)


def _parse_analysis(raw: str) -> TranscriptAnalysis:
    """Parse + sanitize the model's JSON into a deterministic result.

    Raises ``AiInvalidResponseError`` when the output cannot produce the two
    required fields (summary + objection_score); optional fields default to
    their neutral values rather than failing the whole analysis.
    """
    parsed = _parse_json_object(raw)
    if parsed is None:
        raise AiInvalidResponseError("Transcript analysis returned unparseable JSON")

    summary = _clean_text(_as_str(parsed.get("summary")))
    if not summary:
        raise AiInvalidResponseError("Transcript analysis missing a summary")

    score_raw = parsed.get("objection_score")
    if not isinstance(score_raw, (int, float)) or isinstance(score_raw, bool):
        raise AiInvalidResponseError("Transcript analysis missing an objection score")
    score = _clamp_int(score_raw)

    return TranscriptAnalysis(
        summary=summary[:_MAX_STRING_LEN],
        objection_score=score,
        objections=_clean_str_list(parsed.get("objections"), limit=_MAX_OBJECTIONS),
        next_best_action=_optional_text(parsed.get("next_best_action"), _MAX_ACTION_LEN),
        sentiment=_clean_sentiment(parsed.get("sentiment")),
        key_topics=_clean_str_list(parsed.get("key_topics"), limit=_MAX_KEY_TOPICS),
        confidence=_clamp_float(parsed.get("confidence")),
    )


# ---- sanitizers (deterministic authority) ---------------------------------


def _parse_json_object(raw: str) -> dict[str, object] | None:
    """Best-effort parse of a JSON object from LLM output (strip fences)."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean_text(raw: str | None) -> str:
    return "" if raw is None else raw.strip()


def _as_str(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)
    return ""


def _clamp_int(raw: int | float) -> int:
    return max(0, min(100, int(raw)))


def _clamp_float(raw: object) -> float:
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return 0.0
    return round(max(0.0, min(1.0, float(raw))), 3)


def _clean_str_list(raw: object, *, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        value = _clean_text(_as_str(item))[:_MAX_STRING_LEN]
        if value and value not in cleaned:
            cleaned.append(value)
        if len(cleaned) >= limit:
            break
    return cleaned


def _optional_text(raw: object, limit: int) -> str | None:
    value = _clean_text(_as_str(raw))
    if not value:
        return None
    return value[:limit]


def _clean_sentiment(raw: object) -> str:
    value = _as_str(raw).lower()
    return value if value in _SENTIMENT_VALUES else "neutral"
