"""Narration - the (only) LLM touch point for the digest.

Turns the gold-signal dict into a short executive narrative. Unusable LLM
output - invalid JSON, missing fields, transport/provider failures - maps to
``None`` (an abstention), never a hard error. The narrator deliberately refuses
to fabricate numbers: the LLM may only rephrase the signals it is given.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.providers import LlmRequest

if TYPE_CHECKING:
    from ai_agent.core.llm_router import LlmRouter

logger = structlog.get_logger("ai_agent.narrator")

_SYSTEM_PROMPT = (
    "You are Skyrict's executive narrator. You receive a JSON snapshot of a "
    "tenant's Finance, Sales, Inventory and CRM state for one day. Write a "
    "short, specific, plain-language executive digest. NEVER invent numbers "
    "that are not in the snapshot. Return ONLY strict JSON with these keys: "
    '"title" (max 10 words), "summary" (2-3 sentences), "points" (array of '
    '2-4 short bullet strings), "caveat" (one sentence flagging uncertainty or '
    "an empty-aspect warning, or an empty string)."
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class DigestText:
    """The parsed narrative produced by the LLM."""

    title: str
    summary: str
    points: list[str]
    caveat: str
    model_used: str
    latency_ms: int


async def narrate(llm_router: LlmRouter, prompt: str) -> DigestText | None:
    """Generate a digest; return ``None`` on any unusable outcome."""
    started = time.perf_counter()
    try:
        completion = await llm_router.complete(
            LlmRequest(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=prompt,
                max_tokens=600,
                temperature=0.2,
            )
        )
    except Exception:
        logger.warning("narrator.llm_failed")
        return None

    payload = _parse_digest_json(completion.text)
    if payload is None:
        logger.warning("narrator.unparseable")
        return None

    title = str(payload.get("title") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    points_raw = payload.get("points")
    if not title or not summary or not isinstance(points_raw, list) or not points_raw:
        logger.warning("narrator.missing_fields")
        return None
    points = [str(p).strip() for p in points_raw if str(p).strip()]

    return DigestText(
        title=title,
        summary=summary,
        points=points if points else [summary],
        caveat=str(payload.get("caveat") or "").strip(),
        model_used=completion.model_used,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _parse_digest_json(text: str) -> dict[str, object] | None:
    """Strip markdown fences/cruft and parse the first JSON object."""
    match = _JSON_OBJECT_RE.search(text)
    if match is None:
        return None
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None
