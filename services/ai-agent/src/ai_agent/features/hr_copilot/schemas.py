"""Request/response schemas for the HR Copilot endpoint (spec §9)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HrCopilotRequest(BaseModel):
    """POST /ai/hr/copilot/chat body - one message to the Copilot."""

    message: str = Field(min_length=1, max_length=500)


class HrCopilotResponse(BaseModel):
    """POST /ai/hr/copilot/chat response.

    An abstention/refusal is a normal 200 with an ``answer`` (no error), the
    same contract as the NL query endpoint.
    """

    answer: str
    model_used: str | None = None
    latency_ms: int
