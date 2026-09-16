"""Unit tests for the rolling conversation summary service (SKY-100).

Covers: pre-window source selection (incl. the 200-message cap), freshness
checks, prompt building with per-message truncation, fire-and-forget
scheduling, and graceful failures in the background regeneration path (LLM
failure, empty output, missing conversation, store failure).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_agent.core.providers.base import LlmCompletion, LlmRequest
from ai_agent.features.conversation_summary.service import (
    RECENT_WINDOW,
    SUMMARY_MESSAGE_CHAR_CAP,
    SUMMARY_SOURCE_LIMIT,
    _build_summary_prompt,
    _generate_and_persist,
    _select_summary_source,
    is_summary_fresh,
    schedule_summary_regeneration,
)


def _message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def _long_history(count: int) -> list[dict[str, str]]:
    return [_message("user", f"message {index}") for index in range(count)]


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------


class TestSelectSummarySource:
    def test_empty_history(self) -> None:
        assert _select_summary_source([]) == []

    def test_exactly_recent_window_is_not_a_source(self) -> None:
        assert _select_summary_source(_long_history(RECENT_WINDOW)) == []

    def test_under_recent_window_is_not_a_source(self) -> None:
        assert _select_summary_source(_long_history(RECENT_WINDOW - 5)) == []

    def test_pre_window_messages_are_the_source(self) -> None:
        source = _select_summary_source(_long_history(RECENT_WINDOW + 3))
        assert [m["content"] for m in source] == ["message 0", "message 1", "message 2"]

    def test_source_is_capped_to_the_newest_pre_window_messages(self) -> None:
        source = _select_summary_source(_long_history(RECENT_WINDOW + SUMMARY_SOURCE_LIMIT + 50))
        assert len(source) == SUMMARY_SOURCE_LIMIT
        # The cap keeps the newest pre-window span, so the oldest messages
        # fall away (rolling semantics).
        assert source[0]["content"] == "message 50"
        assert source[-1]["content"] == "message 249"


# ---------------------------------------------------------------------------
# Freshness
# ---------------------------------------------------------------------------


class TestIsSummaryFresh:
    def test_none_is_not_fresh(self) -> None:
        assert is_summary_fresh(None) is False

    def test_missing_timestamp_is_not_fresh(self) -> None:
        assert is_summary_fresh({"summary_text": "x"}) is False

    def test_malformed_timestamp_is_not_fresh(self) -> None:
        summary = {"summary_text": "x", "summary_updated_at": "not-a-date"}
        assert is_summary_fresh(summary) is False

    def test_recent_summary_is_fresh(self) -> None:
        updated = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        assert is_summary_fresh({"summary_text": "x", "summary_updated_at": updated}) is True

    def test_old_summary_is_stale(self) -> None:
        updated = (datetime.now(UTC) - timedelta(seconds=7200)).isoformat()
        assert is_summary_fresh({"summary_text": "x", "summary_updated_at": updated}) is False

    def test_naive_timestamp_is_treated_as_utc(self) -> None:
        updated = (datetime.now(UTC) - timedelta(seconds=60)).replace(tzinfo=None).isoformat()
        assert is_summary_fresh({"summary_text": "x", "summary_updated_at": updated}) is True

    def test_respects_injected_now(self) -> None:
        updated = datetime(2026, 1, 1, tzinfo=UTC)
        now = updated + timedelta(seconds=60)
        assert (
            is_summary_fresh(
                {"summary_text": "x", "summary_updated_at": updated.isoformat()}, now=now
            )
            is True
        )


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


class TestBuildSummaryPrompt:
    def test_labels_user_and_assistant_messages(self) -> None:
        prompt = _build_summary_prompt(
            [_message("user", "What stock is low?"), _message("agent", "Stock policy X.")]
        )
        assert "User: What stock is low?" in prompt
        assert "Assistant: Stock policy X." in prompt

    def test_truncates_long_message_content(self) -> None:
        prompt = _build_summary_prompt([_message("user", "x" * 5000)])
        assert "x" * SUMMARY_MESSAGE_CHAR_CAP in prompt
        assert "x" * (SUMMARY_MESSAGE_CHAR_CAP + 1) not in prompt


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


class TestScheduleSummaryRegeneration:
    def test_creates_background_task(self) -> None:
        with patch("asyncio.create_task") as mock_create_task:
            # Close the created coroutine so it never lingers un-awaited
            # (avoids RuntimeWarning noise from the GC).
            mock_create_task.side_effect = lambda coro: coro.close()
            schedule_summary_regeneration(
                conversation_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                llm_router=MagicMock(),
                store_factory=MagicMock(),
            )
            mock_create_task.assert_called_once()


# ---------------------------------------------------------------------------
# Background regeneration
# ---------------------------------------------------------------------------


class _FakeRouter:
    """Mock LLM router that returns a scripted completion."""

    def __init__(self, text: str = "User asked about stock levels twice.") -> None:
        self._text = text
        self.call_count = 0

    async def complete(self, request: LlmRequest, **kwargs: Any) -> LlmCompletion:
        self.call_count += 1
        return LlmCompletion(text=self._text, model_used="test-model", latency_ms=10)


class _FailingRouter:
    """Mock LLM router that always raises."""

    async def complete(self, request: LlmRequest, **kwargs: Any) -> LlmCompletion:
        del request, kwargs
        raise RuntimeError("LLM unavailable")


def _make_store(messages: list[dict[str, str]], *, update_result: bool = True) -> AsyncMock:
    store = AsyncMock()
    store.get_messages = AsyncMock(return_value=messages)
    store.update_summary = AsyncMock(return_value=update_result)
    store.commit = AsyncMock()
    return store


class TestGenerateAndPersist:
    @pytest.mark.asyncio
    async def test_persists_summary_from_pre_window_messages(self) -> None:
        store = _make_store(_long_history(RECENT_WINDOW + 5))
        router = _FakeRouter("User asked about stock twice and decided to reorder.")
        store_factory = AsyncMock(return_value=store)

        await _generate_and_persist(
            conversation_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            llm_router=router,  # type: ignore[arg-type]
            store_factory=store_factory,
        )

        assert router.call_count == 1
        store.update_summary.assert_awaited_once()
        args = store.update_summary.await_args
        assert args is not None
        assert args.kwargs["summary_text"] == "User asked about stock twice and decided to reorder."
        store.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_nothing_to_summarize_skips_llm(self) -> None:
        store = _make_store(_long_history(RECENT_WINDOW))
        router = _FakeRouter()
        store_factory = AsyncMock(return_value=store)

        await _generate_and_persist(
            conversation_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            llm_router=router,  # type: ignore[arg-type]
            store_factory=store_factory,
        )

        assert router.call_count == 0
        store.update_summary.assert_not_awaited()
        store.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_crash_or_persist(self) -> None:
        store = _make_store(_long_history(RECENT_WINDOW + 5))
        store_factory = AsyncMock(return_value=store)

        await _generate_and_persist(
            conversation_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            llm_router=_FailingRouter(),  # type: ignore[arg-type]
            store_factory=store_factory,
        )

        store.update_summary.assert_not_awaited()
        store.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blank_llm_output_does_not_persist(self) -> None:
        store = _make_store(_long_history(RECENT_WINDOW + 5))
        store_factory = AsyncMock(return_value=store)

        await _generate_and_persist(
            conversation_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            llm_router=_FakeRouter("   "),  # type: ignore[arg-type]
            store_factory=store_factory,
        )

        store.update_summary.assert_not_awaited()
        store.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conversation_missing_skips_commit(self) -> None:
        store = _make_store(_long_history(RECENT_WINDOW + 5), update_result=False)
        store_factory = AsyncMock(return_value=store)

        await _generate_and_persist(
            conversation_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            llm_router=_FakeRouter(),  # type: ignore[arg-type]
            store_factory=store_factory,
        )

        store.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_store_failure_does_not_crash(self) -> None:
        store = AsyncMock()
        store.get_messages = AsyncMock(side_effect=RuntimeError("db down"))
        store_factory = AsyncMock(return_value=store)

        await _generate_and_persist(
            conversation_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            llm_router=_FakeRouter(),  # type: ignore[arg-type]
            store_factory=store_factory,
        )

        store.commit.assert_not_awaited()
