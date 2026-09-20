"""/ai/agents/conversations - CRUD for agent-shell conversation persistence.

Replaces the in-memory mock store with PostgreSQL-backed storage so
conversations survive server restarts (SKY-60 durability fix).
"""

from __future__ import annotations

import base64
import binascii
import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.core.config import settings
from ai_agent.db.conversation_repository import ConversationRepository
from ai_agent.features.attachments.storage import (
    AttachmentStoragePort,
    build_attachment_storage,
)
from ai_agent.features.supervisor.title import (
    TitleStore,
    is_conversation_title_retryable,
    schedule_title_generation,
)

logger = structlog.get_logger("ai_agent.conversations")

router = APIRouter(prefix="/ai/agents/conversations", tags=["ai-agent-conversations"])


class _ConversationTitleStore:
    """API-layer adapter from :class:`ConversationRepository` to TitleStore.

    Owns the fresh background session (created by the store factory) and its
    commit, so the ``features`` layer never imports ``ai_agent.db`` (import-
    linter contract: only repositories touch the database layer).
    """

    def __init__(self, repo: ConversationRepository, session: AsyncSession) -> None:
        self._repo = repo
        self._session = session

    async def get_conversation(
        self, *, tenant_id: Any, conversation_id: Any
    ) -> dict[str, Any] | None:
        return await self._repo.get_conversation(
            tenant_id=tenant_id, conversation_id=conversation_id
        )

    async def get_messages(self, *, tenant_id: Any, conversation_id: Any) -> list[dict[str, Any]]:
        return await self._repo.get_messages(tenant_id=tenant_id, conversation_id=conversation_id)

    async def mark_title_generated(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        title: str,
        finalize: bool,
    ) -> bool:
        return await self._repo.mark_title_generated(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            title=title,
            finalize=finalize,
        )

    async def commit(self) -> None:
        await self._session.commit()


async def _title_store_factory() -> TitleStore:
    """Open a fresh session and bind it to a conversation title store."""
    from ai_agent.db.session import async_session_factory

    session = async_session_factory()
    return _ConversationTitleStore(ConversationRepository(session), session)


# ------------------------------------------------------------------
# Request schemas
# ------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    first_prompt: str | None = Field(default=None, max_length=2000)


class AttachmentIn(BaseModel):
    """One file attachment to persist with a user message.

    ``base64`` is the raw base64-encoded content (no data-URL prefix).  The
    server assigns the real storage key; ``id`` is the client-generated id
    used for optimistic UI keys and later lookups through the download
    endpoint.
    """

    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=127)
    size: int = Field(ge=0)
    base64: str = Field(min_length=1)


class AppendMessageRequest(BaseModel):
    role: str = Field(pattern=r"^(user|agent)$")
    content: str = Field(min_length=1, max_length=50000)
    agent_name: str | None = Field(default=None, max_length=128)
    attachments: list[AttachmentIn] | None = Field(
        default=None,
        max_length=10,
        description=(
            "Optional file attachments (user messages only). The server "
            "decodes each base64 payload, stores the blob in the attachment "
            "storage backend, and persists only metadata on the message."
        ),
    )


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    pinned: bool | None = None


async def _store_attachments(
    *,
    storage: AttachmentStoragePort,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    attachments: list[AttachmentIn],
) -> list[dict[str, Any]]:
    """Decode and persist attachment blobs, returning their metadata.

    Each blob is written under the tenant/annotation-scoped key
    ``{tenant_id}/{conversation_id}/{storage_id}`` where ``storage_id`` is a
    server-generated UUID - never the client-supplied id, so clients cannot
    influence object keys.  The returned metadata list (including the storage
    key) is what gets persisted on the message row.
    """
    metadata: list[dict[str, Any]] = []
    for attachment in attachments:
        try:
            data = base64.b64decode(attachment.base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Attachment {attachment.name!r} is not valid base64.",
            ) from exc
        if not data:
            raise HTTPException(
                status_code=422,
                detail=f"Attachment {attachment.name!r} decodes to empty content.",
            )
        if len(data) > settings.ATTACHMENT_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Attachment {attachment.name!r} exceeds the "
                    f"{settings.ATTACHMENT_MAX_BYTES} byte limit."
                ),
            )
        storage_id = str(uuid.uuid4())
        key = f"{tenant_id}/{conversation_id}/{storage_id}"
        await storage.put(key=key, data=data, content_type=attachment.type)
        metadata.append(
            {
                "id": attachment.id,
                "name": attachment.name,
                "type": attachment.type,
                "size": len(data),
                "storage_key": storage_id,
            }
        )
    return metadata


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.get("")
async def list_conversations(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """List all conversations for the current user, pinned first."""
    repo = ConversationRepository(session)
    conversations = await repo.list_conversations(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
    )
    return {"data": conversations}


@router.post("", status_code=201)
async def create_conversation(
    body: CreateConversationRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Create a new conversation, optionally with a first message."""
    repo = ConversationRepository(session)
    title = body.title
    if not title and body.first_prompt:
        # Derive title from the first prompt (truncate to 80 chars).
        title = body.first_prompt[:80].strip()
        if len(body.first_prompt) > 80:
            title += "..."

    conversation = await repo.create_conversation(
        tenant_id=user["tenant_id"],
        user_id=user["user_id"],
        title=title,
    )

    # Optionally append the first user message.
    if body.first_prompt:
        await repo.append_message(
            tenant_id=user["tenant_id"],
            conversation_id=uuid.UUID(conversation["id"]),
            role="user",
            content=body.first_prompt,
        )

    return {"data": conversation}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> dict[str, Any]:
    """Fetch a single conversation with its messages."""
    repo = ConversationRepository(session)
    conversation = await repo.get_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await repo.get_messages(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    conversation["messages"] = messages

    # Retry-on-read: a background title generation may have failed or been
    # skipped. When the title is still retryable, try again on page load so
    # a real title eventually appears even if no new message arrives.
    roles = {message["role"] for message in messages}
    if {"user", "agent"} <= roles and is_conversation_title_retryable(
        conversation["title"],
        conversation["title_generated_at"],
    ):
        schedule_title_generation(
            conversation_id=conversation_id,
            tenant_id=user["tenant_id"],
            llm_router=request.app.state.llm_router,
            store_factory=_title_store_factory,
        )

    return {"data": conversation}


@router.post("/{conversation_id}", status_code=201)
async def append_message(
    conversation_id: uuid.UUID,
    body: AppendMessageRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> dict[str, Any]:
    """Append a message to a conversation."""
    repo = ConversationRepository(session)

    # Verify conversation exists.
    conversation = await repo.get_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Persist attachment blobs BEFORE appending the message: a storage fault
    # fails the request loudly instead of half-persisting a message whose
    # attachments are dangling (SKY-60 attachment durability).
    attachment_metadata: list[dict[str, Any]] = []
    if body.attachments:
        storage = build_attachment_storage()
        attachment_metadata = await _store_attachments(
            storage=storage,
            # Tenant + conversation id come from the fetched DB record, never
            # the request: storage keys are composed solely of server-derived
            # values (mirrors the documents storage pattern).
            tenant_id=uuid.UUID(conversation["tenant_id"]),
            conversation_id=uuid.UUID(conversation["id"]),
            attachments=body.attachments,
        )

    await repo.append_message(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
        role=body.role,
        content=body.content,
        agent_name=body.agent_name,
        attachments=attachment_metadata,
    )

    # Auto-derive title from first user message if title is empty.
    if body.role == "user" and not conversation["title"]:
        title = body.content[:80].strip()
        if len(body.content) > 80:
            title += "..."
        await repo.auto_title(
            tenant_id=user["tenant_id"],
            conversation_id=conversation_id,
            title=title,
        )

    # Schedule AI title generation after an agent reply. Unconditional for
    # every module path (supervisor, module agent, greeting, abstention):
    # the generator produces the deterministic greeting title when the
    # exchange has no topic and keeps non-final states retryable.
    if body.role == "agent" and is_conversation_title_retryable(
        conversation["title"],
        conversation["title_generated_at"],
    ):
        schedule_title_generation(
            conversation_id=conversation_id,
            tenant_id=user["tenant_id"],
            llm_router=request.app.state.llm_router,
            store_factory=_title_store_factory,
        )

    # Return the full conversation (with updated title) so the frontend
    # gets a consistent Conversation object.
    updated = await repo.get_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    return {"data": updated}


@router.get("/{conversation_id}/attachments/{attachment_id}")
async def get_attachment(
    conversation_id: uuid.UUID,
    attachment_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """Serve one conversation attachment's stored blob (tenant-scoped).

    The caller addresses the attachment by its public id; the server resolves
    the storage key from the message metadata, so the object-key namespace is
    never exposed.  A 404 hides whether the conversation, the attachment, or
    the blob is missing (no existence oracle for other tenants).
    """
    repo = ConversationRepository(session)
    meta = await repo.get_attachment_meta(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
        attachment_id=attachment_id,
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    storage = build_attachment_storage()
    # The blob key is prebuilt from the persisted metadata (row-derived
    # tenant/conversation ids + server storage key); the request path params
    # never compose object keys.
    data = await storage.get(key=meta["blob_key"])
    if data is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    safe_name = meta.get("name", "attachment").replace('"', "").replace("\n", "")
    return Response(
        content=data,
        media_type=meta.get("type") or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: uuid.UUID,
    body: UpdateConversationRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Update conversation title or pin state."""
    repo = ConversationRepository(session)

    if body.title is not None:
        ok = await repo.rename_conversation(
            tenant_id=user["tenant_id"],
            conversation_id=conversation_id,
            title=body.title,
        )
    elif body.pinned is not None:
        ok = await repo.set_pin_conversation(
            tenant_id=user["tenant_id"],
            conversation_id=conversation_id,
            pinned=body.pinned,
        )
    else:
        raise HTTPException(status_code=400, detail="No valid update fields provided")

    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation = await repo.get_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    return {"data": conversation}


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a conversation and all its messages (and attachment blobs)."""
    repo = ConversationRepository(session)

    # Remove the blob payloads first (best-effort, never blocks the row
    # delete): the documents service deletes storage before the row, so a
    # deleted conversation cannot leave orphaned blobs behind.  The repository
    # returns full object keys composed from the message rows, so no
    # client-supplied identifier ever composes a storage key.
    storage_keys = await repo.collect_attachment_storage_keys(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    if storage_keys:
        storage = build_attachment_storage()
        for storage_key in storage_keys:
            try:
                await storage.delete(key=storage_key)
            except Exception:
                logger.exception(
                    "attachment_blob_delete_failed",
                    conversation_id=str(conversation_id),
                    storage_key=storage_key,
                )

    ok = await repo.delete_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
