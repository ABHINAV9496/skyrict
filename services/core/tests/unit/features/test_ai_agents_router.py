"""Unit tests for the ``/api/v1/ai/agents`` proxy router (SKY-59).

The permission matrix (invoke/list = erp.ai.invoke; approve/deny =
erp.ai.invoke + erp.finance.write) is enforced by dependency closures, which
are stubbed here — the matrix itself is documented in the router and its
behavior is covered by the identity/integration suites. What this file pins:
path ids are UUIDs BEFORE forwarding (no traversal reaches ai-agent), a
non-UUID interrupt id dies with 422 without any upstream call, and the agent
name travels as a single path segment.
"""

from __future__ import annotations

import uuid

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.features.ai_agents import router as ai_agents_router


def _app_with_recorder(seen: list[httpx.Request]) -> TestClient:
    """App with permission deps stubbed and an upstream that records calls."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    app = FastAPI()
    app.include_router(ai_agents_router.router, prefix="/api/v1")
    app.dependency_overrides[ai_agents_router._require_ai_invoke] = lambda: {"sub": "u1"}
    app.dependency_overrides[ai_agents_router._require_agent_decision] = lambda: {"sub": "u1"}

    client_factory = lambda: httpx.AsyncClient(  # noqa: E731
        transport=httpx.MockTransport(handler), base_url="http://ai.test"
    )
    app.dependency_overrides[ai_agents_router.get_ai_client] = client_factory
    return TestClient(app)


class TestAgentProxyPathShape:
    def test_invoke_forwards_agent_name_to_upstream(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/agents/restock_advisor/invoke",
            headers={"authorization": "Bearer tok"},
            json={"input": {"product_id": "P1"}},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/agents/restock_advisor/invoke"

    def test_list_interrupts_route(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.get(
            "/api/v1/ai/agents/restock_advisor/interrupts",
            headers={"authorization": "Bearer tok"},
        )

        assert response.status_code == 200
        assert seen[0].url.path == "/api/v1/ai/agents/restock_advisor/interrupts"

    def test_valid_uuid_interrupt_id_forwarded_canonically(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        interrupt_id = str(uuid.uuid4())

        response = client.post(
            f"/api/v1/ai/agents/restock_advisor/interrupts/{interrupt_id.upper()}/approve",
            headers={"authorization": "Bearer tok"},
            json={"note": "ok"},
        )

        assert response.status_code == 200
        assert len(seen) == 1
        # Uppercase input reaches ai-agent in canonical lowercase form.
        assert (
            seen[0].url.path
            == f"/api/v1/ai/agents/restock_advisor/interrupts/{interrupt_id}/approve"
        )

    def test_deny_route(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)
        interrupt_id = uuid.uuid4()

        response = client.post(
            f"/api/v1/ai/agents/restock_advisor/interrupts/{interrupt_id}/deny",
            headers={"authorization": "Bearer tok"},
            json={"note": "no"},
        )

        assert response.status_code == 200
        assert (
            seen[0].url.path == f"/api/v1/ai/agents/restock_advisor/interrupts/{interrupt_id}/deny"
        )

    def test_non_uuid_interrupt_id_is_rejected_before_forwarding(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        response = client.post(
            "/api/v1/ai/agents/restock_advisor/interrupts/not-a-uuid/approve",
            headers={"authorization": "Bearer tok"},
        )

        # 422 from FastAPI path-param validation; nothing reached ai-agent.
        assert response.status_code == 422
        assert seen == []

    def test_body_is_relayed_to_upstream(self) -> None:
        seen: list[httpx.Request] = []
        client = _app_with_recorder(seen)

        client.post(
            "/api/v1/ai/agents/restock_advisor/invoke",
            headers={"authorization": "Bearer tok"},
            json={"input": {"product_id": "P1"}},
        )

        assert seen[0].content == b'{"input":{"product_id":"P1"}}'

    def test_chat_stream_forwards_to_supervisor_endpoint(self) -> None:
        """The SSE chat route streams to ai-agent (SKY-60)."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                text=(
                    'event: token\ndata: {"delta": "Hello"}\n\n'
                    'event: done\ndata: {"agents": ["inventory_monitor"]}\n\n'
                ),
                headers={"content-type": "text/event-stream"},
            )

        app = FastAPI()
        app.include_router(ai_agents_router.router, prefix="/api/v1")
        app.dependency_overrides[ai_agents_router._require_ai_invoke] = lambda: {"sub": "u1"}
        client_factory = lambda: httpx.AsyncClient(  # noqa: E731
            transport=httpx.MockTransport(handler), base_url="http://ai.test"
        )
        app.dependency_overrides[ai_agents_router.get_ai_client] = client_factory
        client = TestClient(app)

        response = client.post(
            "/api/v1/ai/agents/chat/stream",
            headers={"authorization": "Bearer tok"},
            json={"message": "stock levels?"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert len(seen) == 1
        assert seen[0].url.path == "/api/v1/ai/agents/chat/stream"
        assert seen[0].content == b'{"message":"stock levels?"}'
        # The SSE frames arrived verbatim, in order.
        assert "event: token" in response.text
        assert response.text.index("event: token") < response.text.index("event: done")
