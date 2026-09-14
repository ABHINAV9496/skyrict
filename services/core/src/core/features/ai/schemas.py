"""Request schemas for the core AI proxy surface (SKY-91 transcript store).

Every other proxy route forwards an unvalidated raw body (ai-agent validates
it at its own door). The transcript write is the exception on purpose: core
persists the transcript into ``erp_crm_activities`` BEFORE forwarding, so an
invalid or oversized body must fail here (422) and never trigger a CRM write
or an upstream LLM call. The bounds mirror ai-agent's ``TranscriptAnalyzeRequest``
so the two services agree on what may be stored.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TranscriptForwardRequest(BaseModel):
    """The transcript body the proxy accepts, then stores + forwards.

    ``transcript`` is the raw call/meeting text. ``min_length=1`` blocks the
    empty payload before any write; ``max_length=60_000`` matches the
    ai-agent engine's ``_MAX_TRANSCRIPT_CHARS`` truncation bound.
    """

    transcript: str = Field(min_length=1, max_length=60_000)
