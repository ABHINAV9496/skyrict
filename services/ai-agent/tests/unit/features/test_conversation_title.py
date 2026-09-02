"""Unit tests for the AI conversation title generation service.

Tests cover: greeting fast-path, normal title generation, non-blocking
scheduling, idempotency (no regeneration of final titles), retryable
non-final states (greeting titles, LLM failures), recovery of the legacy
"New conversation" placeholder, and graceful fallback when the LLM fails.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_agent.core.providers.base import LlmCompletion, LlmRequest
from ai_agent.features.supervisor.title import (
    GREETING_TITLE,
    _build_title_prompt,
    _is_greeting,
    _normalize_title,
    is_conversation_title_retryable,
    schedule_title_generation,
)

# ---------------------------------------------------------------------------
# Pure-function unit tests (no I/O, no DB)
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_strips_whitespace(self) -> None:
        assert _normalize_title("  Inventory Planning  ") == "Inventory Planning"

    def test_removes_wrapping_quotes(self) -> None:
        assert _normalize_title('"Inventory Planning"') == "Inventory Planning"
        assert _normalize_title("'Inventory Planning'") == "Inventory Planning"

    def test_strips_trailing_period(self) -> None:
        assert _normalize_title("Inventory Planning.") == "Inventory Planning"

    def test_strips_trailing_ellipsis(self) -> None:
        assert _normalize_title("Inventory Planning…") == "Inventory Planning"

    def test_strips_trailing_exclamation(self) -> None:
        assert _normalize_title("Inventory Planning!") == "Inventory Planning"

    def test_empty_string(self) -> None:
        assert _normalize_title("") == ""


class TestIsGreeting:
    def test_hi(self) -> None:
        assert _is_greeting("hi") is True

    def test_hey(self) -> None:
        assert _is_greeting("Hey!") is True

    def test_hello_with_period(self) -> None:
        assert _is_greeting("Hello.") is True

    def test_good_morning(self) -> None:
        assert _is_greeting("Good morning!") is True

    def test_greeting_with_whitespace(self) -> None:
        assert _is_greeting("  hi  ") is True

    def test_heyy_is_greeting(self) -> None:
        assert _is_greeting("heyy") is True

    def test_heyyy_with_exclamation_is_greeting(self) -> None:
        assert _is_greeting("heyyy!") is True

    def test_hiii_is_greeting(self) -> None:
        assert _is_greeting("hiii") is True

    def test_greeting_with_question_mark(self) -> None:
        assert _is_greeting("hi?") is True

    def test_not_greeting_with_question(self) -> None:
        assert _is_greeting("hi, what's the inventory status?") is False

    def test_not_greeting_with_content(self) -> None:
        assert _is_greeting("Hey, can you check the low stock items?") is False

    def test_greeting_with_extra_letters_and_content_is_not_greeting(self) -> None:
        assert _is_greeting("heyy, what's the stock level?") is False

    def test_empty_string(self) -> None:
        assert _is_greeting("") is False


class TestIsConversationTitleRetryable:
    def test_null_timestamp_is_retryable(self) -> None:
        assert is_conversation_title_retryable("heyy", None) is True

    def test_final_substantive_title_is_not_retryable(self) -> None:
        assert (
            is_conversation_title_retryable("Stock Level Inquiry", "2026-09-02T00:00:00") is False
        )

    def test_user_rename_is_not_retryable(self) -> None:
        assert is_conversation_title_retryable("My custom title", "2026-09-02T00:00:00") is False

    def test_legacy_placeholder_is_retryable(self) -> None:
        assert is_conversation_title_retryable("New conversation", "2026-09-02T00:00:00") is True


class TestBuildTitlePrompt:
    def test_includes_user_and_assistant_messages(self) -> None:
        prompt = _build_title_prompt("What's the stock level?", "Current stock is 42 units.")
        assert "What's the stock level?" in prompt
        assert "Current stock is 42 units." in prompt

    def test_truncates_long_messages(self) -> None:
        long_msg = "x" * 1000
        prompt = _build_title_prompt(long_msg, "Short reply")
        assert len(prompt) < 1200  # Should be truncated, not 1500+ chars


# ---------------------------------------------------------------------------
# Integration-level tests with mocks (no real DB, no real LLM)
# ---------------------------------------------------------------------------


class _FakeRouter:
    """Mock LLM router that returns a scripted completion."""

    def __init__(self, text: str = "Inventory Planning") -> None:
        self._text = text
        self.call_count = 0

    async def complete(self, request: LlmRequest, **kwargs: Any) -> LlmCompletion:
        self.call_count += 1
        return LlmCompletion(text=self._text, model_used="test-model", latency_ms=10)


class _FailingRouter:
    """Mock LLM router that always raises."""

    async def complete(self, request: LlmRequest, **kwargs: Any) -> LlmCompletion:
        raise RuntimeError("LLM unavailable")


class _FakeSession:
    """Minimal async session mock for background-task tests."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


class TestScheduleTitleGeneration:
    def test_creates_background_task(self) -> None:
        """schedule_title_generation should create a task, not block."""
        with patch("asyncio.create_task") as mock_create_task:
            # Close the created coroutine so it never lingers un-awaited
            # (avoids RuntimeWarning noise from the GC).
            mock_create_task.side_effect = lambda coro: coro.close()
            schedule_title_generation(
                conversation_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                llm_router=_FakeRouter(),
                session_factory=MagicMock(),
            )

            mock_create_task.assert_called_once()


class TestGenerateAndPersist:
    @pytest.mark.asyncio
    async def test_generates_title_after_first_reply(self) -> None:
        """Full flow: conversation with user + agent messages -> title generated."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Mock conversation (no title_generated_at yet)
        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "What's the stock...",
            "title_generated_at": None,
        }
        fake_messages = [
            {"role": "user", "content": "What's the stock level for item X?"},
            {"role": "agent", "content": "The current stock level for item X is 42 units."},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        fake_session = AsyncMock()

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_router = _FakeRouter("Stock Level Inquiry")
            # Create a fake session factory that yields our mock session
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=fake_router,
                session_factory=fake_session_factory,
            )

            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="Stock Level Inquiry",
                finalize=True,
            )

    @pytest.mark.asyncio
    async def test_greeting_skips_llm(self) -> None:
        """Pure greeting -> 'General greeting' without calling LLM."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "hi",
            "title_generated_at": None,
        }
        fake_messages = [
            {"role": "user", "content": "hi"},
            {"role": "agent", "content": "Hello! How can I help you today?"},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        fake_session = AsyncMock()

        fake_router = _FakeRouter("should not be called")

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=fake_router,
                session_factory=fake_session_factory,
            )

            # LLM should NOT have been called; the greeting title must be
            # non-finalizing so a later real question can replace it.
            assert fake_router.call_count == 0
            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title=GREETING_TITLE,
                finalize=False,
            )

    @pytest.mark.asyncio
    async def test_idempotent_skips_if_already_generated(self) -> None:
        """If title_generated_at is already set, do nothing."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "Already Generated Title",
            "title_generated_at": datetime.now(UTC).isoformat(),
        }

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)

        fake_session = AsyncMock()
        fake_router = _FakeRouter("should not be called")

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=fake_router,
                session_factory=fake_session_factory,
            )

            # No messages fetched, no LLM call, no mark_title_generated
            fake_repo.get_messages.assert_not_called()
            assert fake_router.call_count == 0
            fake_repo.mark_title_generated.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_llm_does_not_crash(self) -> None:
        """LLM failure -> readable fallback persisted, still retryable."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "What's the stock...",
            "title_generated_at": None,
        }
        fake_messages = [
            {"role": "user", "content": "What's the stock level?"},
            {"role": "agent", "content": "Stock is low."},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        fake_session = AsyncMock()
        failing_router = _FailingRouter()

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should NOT raise.
            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=failing_router,
                session_factory=fake_session_factory,
            )

            # The fallback is persisted (title never empty) but NOT finalized,
            # so the next turn/page load retries and can replace it.
            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="What's the stock level?",
                finalize=False,
            )
            fake_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_failure_then_retry_succeeds(self) -> None:
        """A failed title call stays retryable; the next attempt finalizes."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "What's the stock...",
            "title_generated_at": None,
        }
        fake_messages = [
            {"role": "user", "content": "What's the stock level?"},
            {"role": "agent", "content": "Stock is low."},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        fake_session = AsyncMock()

        def make_session_factory() -> MagicMock:
            factory = MagicMock()
            factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            factory.return_value.__aexit__ = AsyncMock(return_value=None)
            return factory

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            # First attempt (simulating the failed background task).
            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=_FailingRouter(),
                session_factory=make_session_factory(),
            )
            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="What's the stock level?",
                finalize=False,
            )

            # Second attempt (next turn / page load) succeeds and finalizes.
            fake_repo.reset_mock()
            fake_repo.mark_title_generated = AsyncMock(return_value=True)
            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=_FakeRouter("Stock Level Inquiry"),
                session_factory=make_session_factory(),
            )
            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="Stock Level Inquiry",
                finalize=True,
            )

    @pytest.mark.asyncio
    async def test_blank_llm_output_falls_back_without_finalizing(self) -> None:
        """Empty LLM output falls back to a readable, still-retryable title."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "What's the stock...",
            "title_generated_at": None,
        }
        fake_messages = [
            {"role": "user", "content": "What's the stock level?"},
            {"role": "agent", "content": "Stock is low."},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session = AsyncMock()
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=_FakeRouter("   "),
                session_factory=fake_session_factory,
            )

            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="What's the stock level?",
                finalize=False,
            )

    @pytest.mark.asyncio
    async def test_greeting_then_substantive_titles_from_later_exchange(self) -> None:
        """A greeting followed by a real question titles from the question."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "General greeting",
            "title_generated_at": None,
        }
        fake_messages = [
            {"role": "user", "content": "hi"},
            {"role": "agent", "content": "Hey! How can I help?"},
            {"role": "user", "content": "What's the stock level for item X?"},
            {"role": "agent", "content": "The current stock level for item X is 42 units."},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session = AsyncMock()
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            fake_router = _FakeRouter("Stock Level Inquiry")
            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=fake_router,
                session_factory=fake_session_factory,
            )

            # The LLM was called once (not for the greeting pair) and the
            # title was finalized from the substantive exchange.
            assert fake_router.call_count == 1
            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="Stock Level Inquiry",
                finalize=True,
            )

    @pytest.mark.asyncio
    async def test_legacy_placeholder_stays_retryable(self) -> None:
        """Rows finalized with the old 'New conversation' placeholder heal."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Legacy row: timestamp set, but title is the old placeholder.
        fake_conversation = {
            "id": str(conv_id),
            "tenant_id": str(tenant_id),
            "title": "New conversation",
            "title_generated_at": datetime.now(UTC).isoformat(),
        }
        fake_messages = [
            {"role": "user", "content": "What's the headcount for Q3?"},
            {"role": "agent", "content": "Headcount plans are tracked in HR."},
        ]

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=fake_conversation)
        fake_repo.get_messages = AsyncMock(return_value=fake_messages)
        fake_repo.mark_title_generated = AsyncMock(return_value=True)

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session = AsyncMock()
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=_FakeRouter("Q3 Headcount Planning"),
                session_factory=fake_session_factory,
            )

            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="Q3 Headcount Planning",
                finalize=True,
            )

    @pytest.mark.asyncio
    async def test_conversation_not_found_does_not_crash(self) -> None:
        """If conversation was deleted before background task runs, exit gracefully."""
        from ai_agent.features.supervisor.title import _generate_and_persist

        conv_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        fake_repo = AsyncMock()
        fake_repo.get_conversation = AsyncMock(return_value=None)

        fake_session = AsyncMock()
        fake_router = _FakeRouter()

        with patch(
            "ai_agent.db.conversation_repository.ConversationRepository",
            return_value=fake_repo,
        ):
            fake_session_factory = MagicMock()
            fake_session_factory.return_value.__aenter__ = AsyncMock(return_value=fake_session)
            fake_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            # Should NOT raise
            await _generate_and_persist(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                llm_router=fake_router,
                session_factory=fake_session_factory,
            )

            fake_repo.get_messages.assert_not_called()
            assert fake_router.call_count == 0
