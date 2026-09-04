"""Unit tests for the SSE supervisor chat endpoint (SKY-60, C2a).

The endpoint is exercised through TestClient WITHOUT triggering lifespan
(no DB/Redis pools), with the auth dependency stubbed to a fixed caller and
the supervisor runtime replaced by a scripted fake - so these tests cover the
wire contract (SSE framing, ordering, sanitized error frames, caller binding)
rather than provider internals.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from ai_agent.api.deps import get_current_user
from ai_agent.api.v1.routers import chat
from ai_agent.core.exceptions import AiRateLimitError, AiUnavailableError
from ai_agent.features.supervisor.schemas import (
    AgentStartEvent,
    Citation,
    CitationsEvent,
    ClassificationEvent,
    DoneEvent,
    TokenEvent,
)
from ai_agent.main import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_agent.features.supervisor.schemas import SupervisorEvent

_CALLER = {
    "user_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
    "tenant_id": uuid.UUID("22222222-2222-4222-8222-222222222222"),
    "token_payload": {"sub": "11111111-1111-4111-8111-111111111111"},
}


class _FakeRuntime:
    """Scripted SupervisorRuntime stand-in: yields events or raises once."""

    def __init__(self, events: list[SupervisorEvent] | None = None) -> None:
        self._events = events or []
        self.seen: dict[str, Any] = {}

    async def stream_answer(
        self,
        *,
        query: str,
        attachments: Any = None,
        conversation_id: Any = None,
        tenant_id: Any,
        user_id: Any,
    ) -> AsyncIterator[SupervisorEvent]:
        self.seen = {"query": query, "tenant_id": tenant_id, "user_id": user_id}
        for event in self._events:
            yield event


class _FailingRuntime:
    """Raise the configured exception at the start of the turn."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def stream_answer(
        self,
        *,
        query: str,
        attachments: Any = None,
        conversation_id: Any = None,
        tenant_id: Any,
        user_id: Any,
    ) -> AsyncIterator[SupervisorEvent]:
        raise self._exc
        yield  # pragma: no cover - unreachable; keeps the generator an iterator


def _sse_events(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse ``text/event-stream`` output into (event, payload) pairs."""
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        name = ""
        data_parts: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_parts.append(line.removeprefix("data: "))
        frames.append((name, json.loads("\n".join(data_parts))))
    return frames


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The tenant middleware resolves the tenant slug against Postgres; tests
    # bypass it (endpoint behaviour is covered; the middleware itself has its
    # own tests) and stub the auth dependency with a fixed caller instead.
    monkeypatch.setattr("ai_agent.api.middleware.is_tenant_required_path", lambda _path: False)
    test_client = TestClient(create_app(), raise_server_exceptions=False)
    test_client.app.dependency_overrides[get_current_user] = lambda: _CALLER
    yield test_client
    test_client.app.dependency_overrides.clear()


def _override_runtime(client: TestClient, runtime: _FakeRuntime | _FailingRuntime) -> None:
    client.app.dependency_overrides[chat.get_supervisor_runtime] = lambda: runtime


# --- _to_sse mapping --------------------------------------------------------


def test_to_sse_maps_every_event_type() -> None:
    assert chat._to_sse(
        ClassificationEvent(
            agents=["inventory_monitor"], confidence=0.9, abstain=False, reason=None
        )
    ) == (
        "classification",
        {"agents": ["inventory_monitor"], "confidence": 0.9, "abstain": False, "reason": None},
    )

    assert chat._to_sse(
        AgentStartEvent(agent="inventory_monitor", display_name="Inventory Monitor")
    ) == (
        "agent_start",
        {"agent": "inventory_monitor", "display_name": "Inventory Monitor"},
    )

    assert chat._to_sse(TokenEvent(agent="inventory_monitor", delta="Hello")) == (
        "token",
        {"agent": "inventory_monitor", "delta": "Hello"},
    )

    citation = Citation(
        source_ref="docs/inventory.md",
        module="inventory",
        title="Inventory docs",
        url="/docs/inventory.md",
    )
    assert chat._to_sse(CitationsEvent(agent="inventory_monitor", citations=[citation])) == (
        "citations",
        {
            "agent": "inventory_monitor",
            "citations": [
                {
                    "source_ref": "docs/inventory.md",
                    "module": "inventory",
                    "title": "Inventory docs",
                    "url": "/docs/inventory.md",
                }
            ],
        },
    )

    assert chat._to_sse(DoneEvent(agents=["inventory_monitor"])) == (
        "done",
        {"agents": ["inventory_monitor"]},
    )


# --- HTTP wire contract ------------------------------------------------------


def test_stream_returns_sse_frames_in_order(client: TestClient) -> None:
    events: list[SupervisorEvent] = [
        ClassificationEvent(
            agents=["inventory_monitor"], confidence=0.95, abstain=False, reason=None
        ),
        AgentStartEvent(agent="inventory_monitor", display_name="Inventory Monitor"),
        TokenEvent(agent="inventory_monitor", delta="Aggregating stock"),
        TokenEvent(agent="inventory_monitor", delta=" totals…"),
        DoneEvent(agents=["inventory_monitor"]),
    ]
    _override_runtime(client, _FakeRuntime(events))

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "What's my stock level?", "conversation_id": str(uuid.uuid4())},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    frames = _sse_events(response.text)
    assert [name for name, _ in frames] == [
        "classification",
        "agent_start",
        "token",
        "token",
        "done",
    ]
    assert frames[1][1] == {"agent": "inventory_monitor", "display_name": "Inventory Monitor"}
    assert frames[2][1] == {"agent": "inventory_monitor", "delta": "Aggregating stock"}
    assert frames[-1][1] == {"agents": ["inventory_monitor"]}


def test_stream_binds_runtime_to_caller_identity(client: TestClient) -> None:
    runtime = _FakeRuntime([DoneEvent(agents=["inventory_monitor"])])
    _override_runtime(client, runtime)

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "Summarise"},
    )

    assert response.status_code == 200
    assert runtime.seen["query"] == "Summarise"
    assert runtime.seen["user_id"] == _CALLER["user_id"]
    assert runtime.seen["tenant_id"] == _CALLER["tenant_id"]


def test_stream_sanitizes_ai_unavailable_error(client: TestClient) -> None:
    _override_runtime(
        client,
        _FailingRuntime(AiUnavailableError("openai refused and anthropic is down")),
    )

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "Hello"},
    )

    assert response.status_code == 200
    frames = _sse_events(response.text)
    # The safety done event always fires (even on error) so the frontend
    # knows the stream is over.
    assert frames == [
        ("error", {"message": "The AI service is temporarily unavailable. Please try again."}),
        ("done", {"agents": []}),
    ]
    assert "openai" not in response.text.lower()


def test_stream_sanitizes_unexpected_error(client: TestClient) -> None:
    _override_runtime(
        client,
        _FailingRuntime(RuntimeError("sensitive internal detail: sql://host:5432")),
    )

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "Hello"},
    )

    assert response.status_code == 200
    frames = _sse_events(response.text)
    assert frames == [
        ("error", {"message": "An unexpected error occurred. Please try again."}),
        ("done", {"agents": []}),
    ]
    assert "sensitive" not in response.text
    assert "5432" not in response.text


def test_stream_rejects_blank_message(client: TestClient) -> None:
    # Stub the runtime as well: FastAPI resolves dependencies before body
    # validation, so the real composition root would touch app.state first.
    _override_runtime(client, _FakeRuntime([]))
    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": ""},
    )

    assert response.status_code == 422


# --- C4: per-user + per-tenant chat rate limits ---------------------------------


def test_stream_enforces_user_and_tenant_quota_keys(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, tuple[object, object]] = {}

    async def _fake_enforce(*, key: str, limit: int, window_seconds: int) -> None:
        seen[key] = (limit, window_seconds)

    monkeypatch.setattr(chat.limiter, "enforce", _fake_enforce)
    _override_runtime(client, _FakeRuntime([DoneEvent(agents=["inventory_monitor"])]))

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "hello"},
    )

    assert response.status_code == 200
    user_key = f"ai:chat:{_CALLER['tenant_id']}:{_CALLER['user_id']}"
    tenant_key = f"ai:tenant_total:{_CALLER['tenant_id']}"
    assert set(seen) == {user_key, tenant_key}
    assert seen[user_key][1] == 60
    assert seen[tenant_key][1] == 60


def test_stream_returns_rfc7807_429_when_user_quota_exhausted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_enforce(*, key: str, limit: int, window_seconds: int) -> None:
        raise AiRateLimitError()

    monkeypatch.setattr(chat.limiter, "enforce", _fake_enforce)
    _override_runtime(client, _FakeRuntime([DoneEvent(agents=["inventory_monitor"])]))

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "hello"},
    )

    # The quota is checked BEFORE streaming starts, so this is a normal
    # RFC 7807 error response - never an SSE stream that dies mid-turn.
    assert response.status_code == 429
    assert "ai-rate-limited" in response.text


# --- Lifecycle: terminal state guarantees -----------------------------------


def test_done_event_always_last_after_error(client: TestClient) -> None:
    """A done event MUST follow every error event so the frontend never gets stuck."""
    _override_runtime(
        client,
        _FailingRuntime(AiUnavailableError("provider down")),
    )

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "test"},
    )

    frames = _sse_events(response.text)
    assert frames[-1][0] == "done"
    assert frames[0][0] == "error"


def test_done_event_always_last_after_unexpected_error(client: TestClient) -> None:
    """Even an unhandled exception must be followed by a done event."""
    _override_runtime(
        client,
        _FailingRuntime(RuntimeError("something broke")),
    )

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "test"},
    )

    frames = _sse_events(response.text)
    assert frames[-1][0] == "done"
    assert frames[0][0] == "error"
    # The error message must be human-readable, not a mode string.
    assert "unexpected error" in frames[0][1]["message"].lower()


def test_empty_stream_still_sends_done(client: TestClient) -> None:
    """A stream that yields no events must still close with a done frame."""
    _override_runtime(client, _FakeRuntime([]))

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "empty"},
    )

    frames = _sse_events(response.text)
    assert len(frames) == 1
    assert frames[0] == ("done", {"agents": []})


def test_done_event_not_sent_after_normal_completion(client: TestClient) -> None:
    """When the runtime emits a DoneEvent, the safety net must not duplicate it."""
    events: list[SupervisorEvent] = [
        ClassificationEvent(
            agents=["inventory_monitor"], confidence=0.9, abstain=False, reason=None
        ),
        AgentStartEvent(agent="inventory_monitor", display_name="Inventory Monitor"),
        TokenEvent(agent="inventory_monitor", delta="All good."),
        DoneEvent(agents=["inventory_monitor"]),
    ]
    _override_runtime(client, _FakeRuntime(events))

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "status"},
    )

    frames = _sse_events(response.text)
    done_frames = [f for f in frames if f[0] == "done"]
    assert len(done_frames) == 1
    assert done_frames[0][1] == {"agents": ["inventory_monitor"]}


def test_error_message_does_not_leak_internals(client: TestClient) -> None:
    """Error frames must never contain provider details, connection strings, or stack traces."""
    _override_runtime(
        client,
        _FailingRuntime(
            RuntimeError(
                "psycopg2.OperationalError: connection to server at db.internal:5432 failed"
            )
        ),
    )

    response = client.post(
        "/api/v1/ai/agents/chat/stream",
        json={"message": "leak test"},
    )

    text = response.text.lower()
    assert "psycopg2" not in text
    assert "db.internal" not in text
    assert "5432" not in text
    assert "operationalerror" not in text
