"""SKY-100 supervisor rolling summary: context-budget folding.

Covers the supervisor prompt path when the recent-history window overflows the
supervisor context budget:
- a fresh stored summary is injected at the top and the window is trimmed,
  with no regeneration scheduled;
- a stale summary is injected AND regeneration is scheduled;
- no stored summary trims the window and schedules regeneration;
- an over-budget conversation with no summary store keeps today's behavior
  (full untrimmed window);
- an under-budget conversation never reads the summary store;
- summary-read failures fall back to trimming without crashing the turn.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from tests.unit.test_supervisor_cache import (
    FakeConversationHistory,
    RecordingSupervisorRouter,
    make_service,
)

if TYPE_CHECKING:
    from ai_agent.features.supervisor.schemas import SupervisorEvent
    from ai_agent.features.supervisor.service import SupervisorService

TENANT_A = uuid.uuid4()
USER_ID = uuid.uuid4()

_ELISION_MARKER = "(context trimmed to fit budget)"
_SUMMARY_BLOCK_HEADER = "--- Earlier conversation summary ---"
_CONVERSATION_ID = uuid.uuid4()


class _LongConversationHistory:
    """20 recent messages long enough to overflow the 6000-token budget."""

    def __init__(self, message_count: int = 20, chars: int = 2000) -> None:
        self.get_messages_calls = 0
        self.last_limit: int | None = None
        self._messages = [
            {"role": "user", "content": f"message {index} " + "x" * chars}
            for index in range(message_count)
        ]

    async def get_messages(
        self,
        *,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        del tenant_id, conversation_id
        self.get_messages_calls += 1
        self.last_limit = limit
        return self._messages


class _FakeSummaryStore:
    """Scripted summary store; records reads for the supervisor turn."""

    def __init__(self, summary: dict[str, Any] | None = None, *, raises: bool = False) -> None:
        self._summary = summary
        self._raises = raises
        self.get_summary_calls = 0

    async def get_summary(
        self, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> dict[str, Any] | None:
        del tenant_id, conversation_id
        self.get_summary_calls += 1
        if self._raises:
            raise RuntimeError("db read failed")
        return self._summary


def _fresh_summary(text: str = "Earlier: decided to reorder 500 units.") -> dict[str, Any]:
    updated = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    return {"summary_text": text, "summary_updated_at": updated}


def _stale_summary(text: str = "Earlier: decided to reorder 500 units.") -> dict[str, Any]:
    updated = (datetime.now(UTC) - timedelta(seconds=7200)).isoformat()
    return {"summary_text": text, "summary_updated_at": updated}


class _RegeneratorRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def __call__(self, conversation_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.calls.append((conversation_id, tenant_id))


async def _collect(service: SupervisorService) -> list[SupervisorEvent]:
    return [
        event
        async for event in service.stream_answer(
            query="tell me about multi-turn accounting",
            conversation_id=_CONVERSATION_ID,
            tenant_id=TENANT_A,
            user_id=USER_ID,
        )
    ]


async def test_fresh_summary_injected_and_window_trimmed_no_regeneration() -> None:
    router = RecordingSupervisorRouter()
    store = _FakeSummaryStore(_fresh_summary())
    regenerator = _RegeneratorRecorder()
    service = make_service(
        router=router,
        conversation_history=_LongConversationHistory(),
        conversation_summary=store,
        summary_regenerator=regenerator,
    )

    events = await _collect(service)
    assert events  # the turn completed (abstention answer streamed)
    prompt = router.last_supervisor_prompt

    assert store.get_summary_calls == 1
    assert regenerator.calls == []
    assert prompt is not None
    assert _SUMMARY_BLOCK_HEADER in prompt
    assert "Earlier: decided to reorder 500 units." in prompt
    # The recent window is trimmed: newest messages stay, oldest tail drops,
    # and the elision marker tells the model context was elided.
    assert "User: message 0" in prompt
    assert "User: message 19" not in prompt
    assert _ELISION_MARKER in prompt


async def test_stale_summary_injected_and_regeneration_scheduled() -> None:
    router = RecordingSupervisorRouter()
    store = _FakeSummaryStore(_stale_summary())
    regenerator = _RegeneratorRecorder()
    service = make_service(
        router=router,
        conversation_history=_LongConversationHistory(),
        conversation_summary=store,
        summary_regenerator=regenerator,
    )

    events = await _collect(service)
    assert events  # the turn completed (abstention answer streamed)
    prompt = router.last_supervisor_prompt

    assert store.get_summary_calls == 1
    assert regenerator.calls == [(_CONVERSATION_ID, TENANT_A)]
    assert prompt is not None
    assert _SUMMARY_BLOCK_HEADER in prompt
    assert "Earlier: decided to reorder 500 units." in prompt
    assert _ELISION_MARKER in prompt


async def test_missing_summary_trims_and_schedules_regeneration() -> None:
    router = RecordingSupervisorRouter()
    store = _FakeSummaryStore(None)
    regenerator = _RegeneratorRecorder()
    service = make_service(
        router=router,
        conversation_history=_LongConversationHistory(),
        conversation_summary=store,
        summary_regenerator=regenerator,
    )

    events = await _collect(service)
    assert events  # the turn completed (abstention answer streamed)
    prompt = router.last_supervisor_prompt

    assert store.get_summary_calls == 1
    assert regenerator.calls == [(_CONVERSATION_ID, TENANT_A)]
    assert prompt is not None
    assert _SUMMARY_BLOCK_HEADER not in prompt
    assert _ELISION_MARKER in prompt
    assert "User: message 0" in prompt
    assert "User: message 19" not in prompt


async def test_over_budget_without_summary_store_keeps_today_behavior() -> None:
    """No summary store wired: over-budget history is served untrimmed."""
    router = RecordingSupervisorRouter()
    service = make_service(
        router=router,
        conversation_history=_LongConversationHistory(),
    )

    events = await _collect(service)
    assert events  # the turn completed (abstention answer streamed)
    prompt = router.last_supervisor_prompt

    assert prompt is not None
    assert _SUMMARY_BLOCK_HEADER not in prompt
    assert _ELISION_MARKER not in prompt
    assert "User: message 0" in prompt
    assert "User: message 19" in prompt  # nothing dropped


async def test_under_budget_never_reads_summary() -> None:
    router = RecordingSupervisorRouter()
    store = _FakeSummaryStore(_fresh_summary())
    regenerator = _RegeneratorRecorder()
    service = make_service(
        router=router,
        conversation_history=FakeConversationHistory(message_count=1),
        conversation_summary=store,
        summary_regenerator=regenerator,
    )

    events = await _collect(service)
    assert events  # the turn completed (abstention answer streamed)
    prompt = router.last_supervisor_prompt

    assert store.get_summary_calls == 0
    assert regenerator.calls == []
    assert prompt is not None
    assert _SUMMARY_BLOCK_HEADER not in prompt
    assert _ELISION_MARKER not in prompt
    assert "User: message 0" in prompt


async def test_summary_read_failure_falls_back_to_trim() -> None:
    router = RecordingSupervisorRouter()
    store = _FakeSummaryStore(raises=True)
    regenerator = _RegeneratorRecorder()
    service = make_service(
        router=router,
        conversation_history=_LongConversationHistory(),
        conversation_summary=store,
        summary_regenerator=regenerator,
    )

    events = await _collect(service)
    assert events  # the turn completed (abstention answer streamed)
    prompt = router.last_supervisor_prompt

    # The turn still completes, the window is trimmed, and (best-effort) a
    # regeneration is scheduled since freshness could not be confirmed.
    assert store.get_summary_calls == 1
    assert regenerator.calls == [(_CONVERSATION_ID, TENANT_A)]
    assert prompt is not None
    assert _SUMMARY_BLOCK_HEADER not in prompt
    assert _ELISION_MARKER in prompt
