"""AI-generated conversation title service.

Generates a concise 3-6 word title for a conversation and persists it as a
fire-and-forget background task so the user never waits.

Title lifecycle (set-once for real titles, retryable until then):

- The FIRST substantive exchange (the first non-greeting user message and
  its reply) is titled, regardless of which module path produced the reply
  - supervisor, module agent, greeting or abstention all get a title.
- A clean LLM result is FINAL and recorded via ``title_generated_at``.
- Pure-greeting conversations get the deterministic "General greeting"
  title WITHOUT finalizing, so a later real question still replaces it.
- If the LLM call fails, a readable truncated fallback is persisted WITHOUT
  finalizing and the failure is logged with conversation context; the next
  agent turn or conversation page load retries.
- User renames are final and never overwritten.

The legacy "New conversation" placeholder (rows finalized before this
lifecycle existed) remains retryable so stuck conversations can recover a
real title.
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
- Summarize the core topic of the user's request, not the greeting.
"""

_TITLE_MAX_TOKENS = 16
_TITLE_TEMPERATURE = 0.3

# Older conversations may hold this literal placeholder with a finalized
# timestamp; they must stay retryable so a real exchange can retitle them.
LEGACY_PLACEHOLDER_TITLE = "New conversation"

# Deterministic title for greeting-only conversations. Deliberately NOT
# finalized: a later substantive question replaces it.
GREETING_TITLE = "General greeting"

# Common greetings - fast-path to avoid an LLM call. The pattern is
# permissive on purpose: trailing repeated letters and punctuation ("heyy",
# "hello!" , "hi ?") are still greetings, while ", what's ..." is not.
_GREETING_RE = re.compile(
    (
        r"^\s*(hi+|he+y+|hello+|howdy|yo+|sup|greetings|hola|"
        r"good\s*(morning|afternoon|evening))\s*[!?.\u2026]*\s*$"
    ),
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


def _fallback_title(content: str) -> str:
    """Readable fallback title: the (possibly truncated) user message."""
    title = content[:80].strip()
    if len(content) > 80:
        title += "..."
    return title


def is_conversation_title_retryable(title: str, title_generated_at: str | None) -> bool:
    """True when the AI title generator may still improve this title.

    Substantive AI titles and user renames are final (timestamp present);
    every other state - empty title, greeting-only title, raw fallback, and
    the legacy "New conversation" placeholder - stays retryable.
    """
    return title_generated_at is None or title == LEGACY_PLACEHOLDER_TITLE


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


def _select_substantive_exchange(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """Return the first substantive (non-greeting) user/assistant exchange.

    Greetings carry no topic, so titling deliberately skips greeting pairs;
    when the conversation is still all-greetings this returns empty strings
    and the caller produces the deterministic greeting title instead.
    """
    user_msg = ""
    assistant_msg = ""
    for msg in messages:
        if msg["role"] == "user" and not user_msg and not _is_greeting(msg["content"]):
            user_msg = msg["content"]
        elif msg["role"] == "agent" and user_msg and not assistant_msg:
            assistant_msg = msg["content"]
        if user_msg and assistant_msg:
            break
    return user_msg, assistant_msg


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

            # Idempotence: finalized substantive titles (and user renames)
            # are never touched again. Only the legacy "New conversation"
            # placeholder - a finalized row that predates this lifecycle -
            # remains retryable.
            if not is_conversation_title_retryable(
                conversation["title"],
                conversation["title_generated_at"],
            ):
                return

            messages = await repo.get_messages(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )

            user_msg, assistant_msg = _select_substantive_exchange(messages)

            if not user_msg or not assistant_msg:
                # Greeting-only conversation (or the substantive question has
                # no reply yet). Keep the deterministic title retryable so a
                # real question later replaces "General greeting".
                if conversation["title"] == GREETING_TITLE:
                    return
                title = GREETING_TITLE
                finalized = False
            else:
                prompt = _build_title_prompt(user_msg, assistant_msg)
                try:
                    completion = await llm_router.complete(
                        LlmRequest(
                            system_prompt=_TITLE_SYSTEM_PROMPT,
                            user_prompt=prompt,
                            max_tokens=_TITLE_MAX_TOKENS,
                            temperature=_TITLE_TEMPERATURE,
                        )
                    )
                    title = _normalize_title(completion.text)
                    # Only a clean result is final; empty or over-long output
                    # falls back WITHOUT finalizing so a retry can improve it.
                    finalized = bool(title) and len(title) <= 60
                    if not finalized:
                        title = _fallback_title(user_msg)
                except Exception as exc:
                    # Transient provider/rate-limit failure: keep a readable
                    # fallback, record why for operators, and leave the
                    # conversation retryable (next turn or page load).
                    title = _fallback_title(user_msg)
                    finalized = False
                    logger.warning(
                        "title_generation_llm_failed",
                        conversation_id=str(conversation_id),
                        error=type(exc).__name__,
                        exc_info=True,
                    )

            updated = await repo.mark_title_generated(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                title=title,
                finalize=finalized,
            )
            if updated:
                await session.commit()
                if finalized:
                    logger.info(
                        "title_generated",
                        conversation_id=str(conversation_id),
                        title=title,
                    )
                else:
                    logger.info(
                        "title_generation_deferred",
                        conversation_id=str(conversation_id),
                        title=title,
                    )
            else:
                # A final title appeared while we were working - harmless.
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

    Call this from the ``append_message`` endpoint after an agent reply is
    persisted (and from conversation page loads while the title is still
    retryable).  Uses ``asyncio.create_task`` so the HTTP response is
    returned immediately.
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
