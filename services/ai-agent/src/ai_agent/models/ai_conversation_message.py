"""ai_conversation_messages - ordered message log per conversation.

Each row is one user or agent message within a conversation.  Messages
cascade-delete when the parent conversation is removed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_agent.models.base import Base


class AiConversationMessage(Base):
    """One message in an agent-shell conversation."""

    __tablename__ = "ai_conversation_messages"
    __table_args__ = (
        # Parent PK is composite (tenant_id, id) - the FK must be composite
        # too; a single-column FK to id alone would fail DDL on Postgres.
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["ai_conversations.tenant_id", "ai_conversations.id"],
            ondelete="CASCADE",
        ),
        Index(
            "idx_conversation_messages_tenant_conv",
            "tenant_id",
            "conversation_id",
            "created_at",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="'user' or 'agent'")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="Module agent that answered"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
