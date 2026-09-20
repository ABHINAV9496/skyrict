"""Conversation repository - CRUD for agent-shell conversations.

Handles creating, listing, updating, and deleting conversations and their
messages.  All methods are tenant-scoped via ``tenant_id``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import delete, desc, or_, select, update

from ai_agent.models.ai_conversation import AiConversation
from ai_agent.models.ai_conversation_message import AiConversationMessage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger("ai_agent.conversation_repo")

# Conversations finalized BEFORE the non-finalizing greeting title existed may
# still carry this literal placeholder with a set ``title_generated_at``.
# Such rows must stay retryable so a real exchange can replace the
# placeholder (see ai_agent.features.supervisor.title).
LEGACY_PLACEHOLDER_TITLE = "New conversation"


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
        """Update the conversation title. Returns True if a row was updated.

        A user rename is final: ``title_generated_at`` is recorded so the AI
        title generator never overwrites the user's choice.
        """
        from datetime import UTC, datetime

        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
            )
            .values(
                title=title,
                title_generated_at=datetime.now(UTC),
            )
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
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Append a message to a conversation and touch updated_at.

        ``attachments`` is the list of persisted attachment metadata
        ``{id, name, type, size, storage_key}`` (blobs already stored in the
        attachment storage backend by the API layer).
        """
        msg = AiConversationMessage(
            tenant_id=tenant_id,
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent_name=agent_name,
            attachments=attachments or [],
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
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch messages for a conversation, ordered by created_at ASC.

        When ``limit`` is given, only the most recent ``limit`` messages are
        returned (ordered ASC for callers that render oldest-first). Without
        a limit the full history is returned - the conversations list endpoint
        and the title feature need the complete (or earliest) exchange, so the
        bounded default is only applied by callers that explicitly ask for it
        (the supervisor history window, SKY-100).
        """
        stmt = (
            select(AiConversationMessage)
            .where(
                AiConversationMessage.tenant_id == tenant_id,
                AiConversationMessage.conversation_id == conversation_id,
            )
            .order_by(AiConversationMessage.created_at)
        )
        if limit is not None:
            # Most-recent N: order DESC + LIMIT in SQL, then reverse in memory
            # so the returned list stays ASC (oldest-first) - the supervisor
            # renders history oldest-first for the prompt.
            stmt = stmt.order_by(desc(AiConversationMessage.created_at)).limit(limit)
            result = await self._session.execute(stmt)
            return [_message_to_dict(row) for row in reversed(result.scalars().all())]
        result = await self._session.execute(stmt)
        return [_message_to_dict(row) for row in result.scalars().all()]

    async def get_attachment_meta(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        attachment_id: str,
    ) -> dict[str, Any] | None:
        """Resolve one persisted attachment's metadata within a conversation.

        Confirms the conversation exists first (403/404 semantics differ by
        caller), then scans the conversation's messages for an attachment
        whose id matches.  Returns the full stored metadata
        (``{id, name, type, size, storage_key, blob_key}``) or None when the
        attachment is not part of this conversation.
        """
        conversation = await self.get_conversation(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
        )
        if conversation is None:
            return None
        stmt = select(AiConversationMessage).where(
            AiConversationMessage.tenant_id == tenant_id,
            AiConversationMessage.conversation_id == conversation_id,
        )
        result = await self._session.execute(stmt)
        for row in result.scalars().all():
            for attachment in row.attachments or []:
                if attachment.get("id") == attachment_id:
                    # The full object key is composed here from DB row values
                    # only: the caller passes it verbatim to storage, so no
                    # request-derived identifier can influence object keys.
                    return {
                        **dict(attachment),
                        "blob_key": (
                            f"{row.tenant_id}/{row.conversation_id}/{attachment.get('storage_key')}"
                        ),
                    }
        return None

    async def collect_attachment_storage_keys(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> list[str]:
        """Return the full object key of every attachment blob across the
        conversation's messages, for cleanup when the conversation is
        deleted.

        Keys are composed from DB row values only (``{tenant_id}/
        {conversation_id}/{storage_key}``), so no request-derived identifier
        can influence them.  ``[]`` when the conversation has no messages.
        """
        stmt = select(AiConversationMessage).where(
            AiConversationMessage.tenant_id == tenant_id,
            AiConversationMessage.conversation_id == conversation_id,
        )
        result = await self._session.execute(stmt)
        keys: list[str] = []
        for row in result.scalars().all():
            for attachment in row.attachments or []:
                storage_key = attachment.get("storage_key")
                if storage_key:
                    keys.append(f"{row.tenant_id}/{row.conversation_id}/{storage_key}")
        return keys

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

    # ------------------------------------------------------------------
    # Rolling summary (SKY-100)
    # ------------------------------------------------------------------

    async def get_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        """Fetch the rolling summary for a conversation, or None.

        The summary is an internal context-compaction detail and is
        deliberately NOT part of ``_conversation_to_dict`` - callers outside
        the supervisor prompt path never see it.
        """
        stmt = select(AiConversation).where(
            AiConversation.tenant_id == tenant_id,
            AiConversation.id == conversation_id,
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None or row.summary_text is None:
            return None
        return {
            "summary_text": row.summary_text,
            "summary_updated_at": row.summary_updated_at.isoformat()
            if row.summary_updated_at
            else None,
        }

    async def update_summary(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        summary_text: str,
    ) -> bool:
        """Replace the rolling summary and stamp the regeneration time."""
        from datetime import UTC, datetime

        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
            )
            .values(
                summary_text=summary_text,
                summary_updated_at=datetime.now(UTC),
            )
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def mark_title_generated(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        title: str,
        finalize: bool = True,
    ) -> bool:
        """Persist the AI title, optionally recording the generation time.

        Idempotent: the write only applies while the conversation title is
        still retryable - no final title exists yet, or the row still holds
        the legacy ``New conversation`` placeholder (rows that predate the
        non-finalizing greeting title). ``finalize=False`` is used for
        greeting-only titles and LLM-failure fallbacks: the readable title is
        persisted but ``title_generated_at`` is cleared/kept NULL so a later
        substantive generation can still replace it.
        """
        from datetime import UTC, datetime

        values: dict[str, Any] = {"title": title}
        values["title_generated_at"] = datetime.now(UTC) if finalize else None

        stmt = (
            update(AiConversation)
            .where(
                AiConversation.tenant_id == tenant_id,
                AiConversation.id == conversation_id,
                or_(
                    AiConversation.title_generated_at.is_(None),
                    AiConversation.title == LEGACY_PLACEHOLDER_TITLE,
                ),
            )
            .values(**values)
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
    # Public attachment metadata.  The internal storage_key object key never
    # leaves the API - the download endpoint resolves it server-side only.
    attachments = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("type"),
            "size": a.get("size"),
        }
        for a in (row.attachments or [])
    ]
    return {
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "role": row.role,
        "content": row.content,
        "agent_name": row.agent_name,
        "attachments": attachments,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
