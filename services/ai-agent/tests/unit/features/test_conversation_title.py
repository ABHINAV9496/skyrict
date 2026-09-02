"""Unit tests for the AI conversation title generation service.

Tests cover: greeting fast-path, normal title generation, non-blocking
scheduling, idempotency (no regeneration on 2nd message), and graceful
fallback when the LLM call fails.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_agent.core.providers.base import LlmCompletion, LlmRequest
from ai_agent.features.supervisor.title import (
    _build_title_prompt,
    _is_greeting,
    _normalize_title,
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

    def test_not_greeting_with_question(self) -> None:
        assert _is_greeting("hi, what's the inventory status?") is False

    def test_not_greeting_with_content(self) -> None:
        assert _is_greeting("Hey, can you check the low stock items?") is False

    def test_empty_string(self) -> None:
        assert _is_greeting("") is False


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
            )

    @pytest.mark.asyncio
    async def test_greeting_skips_llm(self) -> None:
        """Pure greeting -> 'New conversation' without calling LLM."""
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

            # LLM should NOT have been called
            assert fake_router.call_count == 0
            fake_repo.mark_title_generated.assert_called_once_with(
                tenant_id=tenant_id,
                conversation_id=conv_id,
                title="New conversation",
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
        """LLM failure -> exception caught, fallback title kept."""
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

        fake_session = AsyncMock()
        failing_router = _FailingRouter()

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
                llm_router=failing_router,
                session_factory=fake_session_factory,
            )

            # No title update attempted
            fake_repo.mark_title_generated.assert_not_called()

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
