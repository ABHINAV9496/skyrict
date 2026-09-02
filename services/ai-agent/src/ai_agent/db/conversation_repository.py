"""Conversation repository — CRUD for agent-shell conversations.

Handles creating, listing, updating, and deleting conversations and their
messages.  All methods are tenant-scoped via ``tenant_id``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import delete, desc, select, update

from ai_agent.models.ai_conversation import AiConversation
from ai_agent.models.ai_conversation_message import AiConversationMessage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.conversation_repo")


class ConversationRepository:
    """Tenant-scoped read/write for agent-shell conversations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    async def create_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str = "",
    ) -> dict[str, Any]:
        """Create a new conversation and return it as a dict."""
        row = AiConversation(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
        )
        self._session.add(row)
        await self._session.flush()
        logger.info("conversation_created", conversation_id=str(row.id))
        return _conversation_to_dict(row)

    async def get_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Fetch a single conversation by ID."""
        stmt = select(AiConversation).where(
            AiConversation.tenant_id == tenant_id,
            AiConversation.id == conversation_id,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _conversation_to_dict(row) if row else None

    async def list_conversations(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """List all conversations for a user, pinned first then by recency."""
        stmt = (
            select(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.user_id == user_id,
            )
            .order_by(
                desc(AiConversation.pinned),
                desc(AiConversation.updated_at),
            )
        )
        result = await self._session.execute(stmt)
        return [_conversation_to_dict(row) for row in result.scalars().all()]

    async def rename_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str,
    ) -> bool:
        """Update the conversation title. Returns True if a row was updated."""
        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
            )
            .values(title=title)
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def toggle_pin_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> bool:
        """Toggle the pinned state. Returns True if a row was updated."""
        # Fetch current state first.
        current = await self.get_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        if current is None:
            return False
        new_pinned = not current["pinned"]
        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
            )
            .values(pinned=new_pinned)
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def set_pin_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        pinned: bool,
    ) -> bool:
        """Set the pinned state to a specific value. Returns True if updated."""
        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
            )
            .values(pinned=pinned)
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def delete_conversation(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> bool:
        """Delete a conversation and its messages (cascade). Returns True if deleted."""
        stmt = delete(AiConversation).where(
            AiConversation.tenant_id == tenant_id,
            AiConversation.id == conversation_id,
        )
        result = await self._session.execute(stmt)
        deleted = bool(result.rowcount)  # type: ignore[attr-defined]
        if deleted:
            logger.info("conversation_deleted", conversation_id=str(conversation_id))
        return deleted

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def append_message(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        agent_name: str | None = None,
    ) -> dict[str, Any]:
        """Append a message to a conversation and touch updated_at."""
        msg = AiConversationMessage(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent_name=agent_name,
        )
        self._session.add(msg)

        # Touch the conversation's updated_at for sort order.
        from datetime import UTC, datetime

        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
            )
            .values(updated_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return _message_to_dict(msg)

    async def get_messages(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Fetch all messages for a conversation, ordered by created_at ASC."""
        stmt = (
            select(AiConversationMessage)
            .where(
                AiConversationMessage.tenant_id == tenant_id,
                AiConversationMessage.conversation_id == conversation_id,
            )
            .order_by(AiConversationMessage.created_at)
        )
        result = await self._session.execute(stmt)
        return [_message_to_dict(row) for row in result.scalars().all()]

    async def auto_title(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str,
    ) -> None:
        """Set the conversation title if it is currently empty."""
        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
                AiConversation.title == "",
            )
            .values(title=title)
        )
        await self._session.execute(stmt)

    async def mark_title_generated(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str,
    ) -> bool:
        """Set the AI-generated title and record the generation timestamp.

        Idempotent: only updates when ``title_generated_at IS NULL``.
        Returns True if a row was actually updated.
        """
        from datetime import UTC, datetime

        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
                AiConversation.title_generated_at.is_(None),
            )
            .values(
                title=title,
                title_generated_at=datetime.now(UTC),
            )
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _conversation_to_dict(row: AiConversation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "user_id": str(row.user_id),
        "title": row.title,
        "title_generated_at": row.title_generated_at.isoformat()
        if row.title_generated_at
        else None,
        "pinned": row.pinned,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _message_to_dict(row: AiConversationMessage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "role": row.role,
        "content": row.content,
        "agent_name": row.agent_name,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
