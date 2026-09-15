"""Rolling summary generation and persistence (SKY-100).

The supervisor only injects the most recent ``RECENT_WINDOW`` messages
verbatim. When that window alone overflows the supervisor context budget, the
store's rolling summary stands in for everything older. This module owns the
pure logic (source selection, prompt building, freshness checks) and the
fire-and-forget regeneration schedule; persistence goes through the
``ConversationSummaryStore`` port so the feature layer never imports
``ai_agent.db`` (import-linter contract).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from ai_agent.core.providers.base import LlmRequest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ai_agent.core.llm_router import LlmRouter

logger = structlog.get_logger("ai_agent.conversation_summary")

# Matches supervisor.service._HISTORY_MESSAGE_LIMIT: the recent window is
# injected verbatim and is NOT part of the summary source.
RECENT_WINDOW = 20
# Cap on pre-window messages summarized per regeneration. Bounds the
# background LLM call so a very long conversation cannot produce an unbounded
# prompt. Rolling semantics: the oldest pre-window content falls away.
SUMMARY_SOURCE_LIMIT = 200
# Regenerate the summary when it is older than this.
SUMMARY_FRESHNESS_SECONDS = 3600
# Per-message character cap when building the summarization prompt; bounds the
# background call further (LIMIT * CAP stays well inside provider context).
SUMMARY_MESSAGE_CHAR_CAP = 200

_SUMMARY_SYSTEM_PROMPT = """\
You write a compact rolling summary of an earlier chat conversation.

Rules:
- Output ONLY the summary text, nothing else.
- 3 to 8 sentences, plain prose, no headers.
- Preserve concrete facts: names, quantities, decisions, commitments, and
  unresolved follow-ups the user may reference later.
- Do not address the reader or mention that this is a summary.
"""

_SUMMARY_MAX_TOKENS = 512
_SUMMARY_TEMPERATURE = 0.3


class ConversationSummaryStore(Protocol):
    """Persistence surface the summary generator needs.

    Lives here so ``features`` never imports ``ai_agent.db`` directly. The
    composition root adapts :class:`ConversationRepository` (or a fresh-session
    adapter) to this protocol.
    """

    async def get_summary(
        self, *, tenant_id: Any, conversation_id: Any
    ) -> dict[str, Any] | None: ...

    async def get_messages(
        self, *, tenant_id: Any, conversation_id: Any, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def update_summary(
        self, *, tenant_id: Any, conversation_id: Any, summary_text: str
    ) -> bool: ...

    async def commit(self) -> None: ...


def is_summary_fresh(summary: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """True when a stored summary exists and was regenerated recently.

    A summary with no timestamp is treated as stale so a regeneration gets
    scheduled and the timestamp gets populated.
    """
    if summary is None:
        return False
    raw = summary.get("summary_updated_at")
    if not raw:
        return False
    try:
        updated_at = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now - updated_at <= timedelta(seconds=SUMMARY_FRESHNESS_SECONDS)


def _select_summary_source(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages immediately preceding the recent window, capped.

    Everything before the last ``RECENT_WINDOW`` messages is the summary's
    source - that is the span the supervisor prompt no longer shows. Only the
    newest ``SUMMARY_SOURCE_LIMIT`` of that span is taken, so regeneration cost
    stays bounded as the conversation grows.
    """
    if len(messages) <= RECENT_WINDOW:
        return []
    pre_window = messages[: len(messages) - RECENT_WINDOW]
    return pre_window[-SUMMARY_SOURCE_LIMIT:]


def _build_summary_prompt(messages: list[dict[str, Any]]) -> str:
    """Render pre-window messages into the summarization user prompt."""
    lines: list[str] = []
    for msg in messages:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = str(msg.get("content", ""))[:SUMMARY_MESSAGE_CHAR_CAP]
        lines.append(f"{role}: {content}")
    return "Earlier conversation:\n" + "\n".join(lines) + "\n\nSummarize it."


async def _generate_and_persist(
    *,
    conversation_id: Any,
    tenant_id: Any,
    llm_router: LlmRouter,
    store_factory: Callable[[], Awaitable[ConversationSummaryStore]],
) -> None:
    """Regenerate the summary in a fresh session, then persist it.

    Runs entirely outside the request scope so it does not block the response
    or participate in the request's transaction. ``store_factory`` comes from
    the composition layer, keeping this module free of database imports.
    """
    try:
        store = await store_factory()
        messages = await store.get_messages(tenant_id=tenant_id, conversation_id=conversation_id)
        source = _select_summary_source(messages)
        if not source:
            logger.debug(
                "summary.regeneration_nothing_to_summarize",
                conversation_id=str(conversation_id),
            )
            return
        try:
            completion = await llm_router.complete(
                LlmRequest(
                    system_prompt=_SUMMARY_SYSTEM_PROMPT,
                    user_prompt=_build_summary_prompt(source),
                    max_tokens=_SUMMARY_MAX_TOKENS,
                    temperature=_SUMMARY_TEMPERATURE,
                )
            )
        except Exception:
            logger.warning(
                "summary.regeneration_llm_failed",
                conversation_id=str(conversation_id),
                exc_info=True,
            )
            return
        summary_text = (completion.text or "").strip()
        if not summary_text:
            logger.warning(
                "summary.regeneration_empty",
                conversation_id=str(conversation_id),
            )
            return
        updated = await store.update_summary(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            summary_text=summary_text,
        )
        if updated:
            await store.commit()
            logger.info(
                "summary.regenerated",
                conversation_id=str(conversation_id),
            )
        else:
            logger.debug(
                "summary.conversation_missing",
                conversation_id=str(conversation_id),
            )
    except Exception:
        logger.exception(
            "summary.regeneration_failed",
            conversation_id=str(conversation_id),
            exc_info=True,
        )


def schedule_summary_regeneration(
    *,
    conversation_id: Any,
    tenant_id: Any,
    llm_router: LlmRouter,
    store_factory: Callable[[], Awaitable[ConversationSummaryStore]],
) -> None:
    """Fire-and-forget background summary regeneration.

    Schedules with ``asyncio.create_task`` so the caller's turn continues
    immediately; the task owns its own session for the lifetime of the work.
    """
    import asyncio

    task = asyncio.create_task(
        _generate_and_persist(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            llm_router=llm_router,
            store_factory=store_factory,
        )
    )
    logger.debug(
        "summary.regeneration_scheduled",
        conversation_id=str(conversation_id),
        task=task,
    )
