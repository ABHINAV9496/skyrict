"""AI-generated conversation title service.

Generates a concise 3-6 word title after the first assistant reply.
Runs as a fire-and-forget background task so the user never waits.

The title replaces the truncated first-prompt fallback stored at creation
time. Idempotent: ``title_generated_at`` column guards against duplicate
generation. Graceful: if the LLM call fails, the fallback title is kept.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import structlog

from ai_agent.core.providers.base import LlmRequest

if TYPE_CHECKING:
    from ai_agent.core.llm_router import LlmRouter

logger = structlog.get_logger("ai_agent.title")

_TITLE_SYSTEM_PROMPT = """\
You generate short, descriptive titles for chat conversations.

Rules:
- Output ONLY the title text, nothing else.
- 3 to 6 words, sentence case.
- No trailing period, no quotation marks, no em dash.
- Summarize the core topic, not the greeting.
- If the conversation is ONLY a greeting with no real question, output exactly: New conversation\
"""

_TITLE_MAX_TOKENS = 16
_TITLE_TEMPERATURE = 0.3

# Common greetings — fast-path to avoid an LLM call.
_GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|howdy|good\s*(morning|afternoon|evening)|yo|sup|greetings)\s*[!.…]*\s*$",
    re.IGNORECASE,
)


def _normalize_title(raw: str) -> str:
    """Strip whitespace and trailing punctuation from the raw LLM output."""
    title = raw.strip()
    # Remove wrapping quotes if present.
    if (title.startswith('"') and title.endswith('"')) or (
        title.startswith("'") and title.endswith("'")
    ):
        title = title[1:-1].strip()
    # Strip trailing period / ellipsis.
    title = re.sub(r"[.!?…]+$", "", title).strip()
    return title


def _is_greeting(content: str) -> bool:
    """True when the message is purely a greeting with no substantive question."""
    return bool(_GREETING_RE.match(content))


def _build_title_prompt(
    user_msg: str,
    assistant_msg: str,
) -> str:
    """Build the user-prompt for the title LLM call."""
    return (
        "Conversation so far:\n"
        f"User: {user_msg[:500]}\n"
        f"Assistant: {assistant_msg[:500]}\n\n"
        "Generate a short title for this conversation."
    )


async def _generate_and_persist(
    *,
    conversation_id: Any,
    tenant_id: Any,
    llm_router: LlmRouter,
    session_factory: Any,
) -> None:
    """Open a fresh DB session, generate the title, and persist it.

    Runs entirely outside the request scope so it does not block the
    response or participate in the request's transaction.
    """
    try:
        async with session_factory() as session:
            from ai_agent.db.conversation_repository import ConversationRepository

            repo = ConversationRepository(session)
            conversation = await repo.get_conversation(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )
            if conversation is None:
                logger.warning(
                    "title_generation_conversation_not_found",
                    conversation_id=str(conversation_id),
                )
                return

            # Idempotent guard: skip if already generated.
            if conversation["title_generated_at"] is not None:
                return

            messages = await repo.get_messages(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )

            user_msg = ""
            assistant_msg = ""
            for msg in messages:
                if msg["role"] == "user" and not user_msg:
                    user_msg = msg["content"]
                elif msg["role"] == "agent" and not assistant_msg:
                    assistant_msg = msg["content"]
                if user_msg and assistant_msg:
                    break

            if not user_msg or not assistant_msg:
                logger.warning(
                    "title_generation_missing_messages",
                    conversation_id=str(conversation_id),
                )
                return

            # Fast-path: pure greeting → "New conversation".
            if _is_greeting(user_msg):
                title = "New conversation"
            else:
                prompt = _build_title_prompt(user_msg, assistant_msg)
                completion = await llm_router.complete(
                    LlmRequest(
                        system_prompt=_TITLE_SYSTEM_PROMPT,
                        user_prompt=prompt,
                        max_tokens=_TITLE_MAX_TOKENS,
                        temperature=_TITLE_TEMPERATURE,
                    )
                )
                title = _normalize_title(completion.text)
                if not title or len(title) > 60:
                    # Fallback: truncate first prompt.
                    title = user_msg[:80].strip()
                    if len(user_msg) > 80:
                        title += "..."

            updated = await repo.mark_title_generated(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                title=title,
            )
            if updated:
                await session.commit()
                logger.info(
                    "title_generated",
                    conversation_id=str(conversation_id),
                    title=title,
                )
            else:
                # Another worker beat us to it — harmless.
                logger.debug(
                    "title_already_generated",
                    conversation_id=str(conversation_id),
                )
    except Exception:
        logger.exception(
            "title_generation_failed",
            conversation_id=str(conversation_id),
            exc_info=True,
        )


def schedule_title_generation(
    *,
    conversation_id: Any,
    tenant_id: Any,
    llm_router: LlmRouter,
    session_factory: Any,
) -> None:
    """Fire-and-forget background title generation.

    Call this from the ``append_message`` endpoint after the first agent
    reply is persisted.  Uses ``asyncio.create_task`` so the HTTP response
    is returned immediately.
    """
    import asyncio

    task = asyncio.create_task(
        _generate_and_persist(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            llm_router=llm_router,
            session_factory=session_factory,
        )
    )
    logger.debug(
        "title_generation_scheduled",
        conversation_id=str(conversation_id),
        task=task,
    )
