"""/ai/agents/conversations — CRUD for agent-shell conversation persistence.

Replaces the in-memory mock store with PostgreSQL-backed storage so
conversations survive server restarts (SKY-60 durability fix).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.api.deps import get_current_user, get_db
from ai_agent.db.conversation_repository import ConversationRepository

router = APIRouter(prefix="/ai/agents/conversations", tags=["ai-agent-conversations"])


# ------------------------------------------------------------------
# Request schemas
# ------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    first_prompt: str | None = Field(default=None, max_length=2000)


class AppendMessageRequest(BaseModel):
    role: str = Field(pattern=r"^(user|agent)$")
    content: str = Field(min_length=1, max_length=50000)
    agent_name: str | None = Field(default=None, max_length=128)


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    pinned: bool | None = None


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

    await repo.append_message(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
        role=body.role,
        content=body.content,
        agent_name=body.agent_name,
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

    # Schedule AI title generation after the first agent reply.
    if body.role == "agent" and conversation["title_generated_at"] is None:
        from ai_agent.db.session import async_session_factory
        from ai_agent.features.supervisor.title import schedule_title_generation

        schedule_title_generation(
            conversation_id=conversation_id,
            tenant_id=user["tenant_id"],
            llm_router=request.app.state.llm_router,
            session_factory=async_session_factory,
        )

    # Return the full conversation (with updated title) so the frontend
    # gets a consistent Conversation object.
    updated = await repo.get_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    return {"data": updated}


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
    """Delete a conversation and all its messages."""
    repo = ConversationRepository(session)
    ok = await repo.delete_conversation(
        tenant_id=user["tenant_id"],
        conversation_id=conversation_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
