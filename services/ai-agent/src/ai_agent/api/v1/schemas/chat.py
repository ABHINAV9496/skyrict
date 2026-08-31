"""Request/response schemas for the Agents-shell chat stream (SKY-60)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ChatStreamRequest(BaseModel):
    """POST /ai/agents/chat/stream body — one turn for the supervisor."""

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
