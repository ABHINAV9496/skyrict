"""Request/response schemas for the Agents-shell chat stream (SKY-60)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AttachmentData(BaseModel):
    """A file attachment sent with a chat message.

    Contains the base64-encoded content so the ai-agent can extract text
    (for documents) or pass image data directly to a vision-capable LLM.
    """

    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=127)
    size: int = Field(ge=0)
    base64: str = Field(
        min_length=1, description="Base64-encoded file content (no data-URL prefix)."
    )


class ChatStreamRequest(BaseModel):
    """POST /ai/agents/chat/stream body - one turn for the supervisor."""

    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None
    attachments: list[AttachmentData] | None = Field(
        default=None,
        max_length=10,
        description="Optional file attachments (images, documents). Max 10 per turn.",
    )
