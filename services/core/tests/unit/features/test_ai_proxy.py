"""Unit tests for the AI proxy transport layer (core.features.ai.proxy).

Uses ``httpx.MockTransport`` — no FastAPI client, matching the repo's
unit-test style (pure logic, real dependency stacks covered by the
integration suite).
"""

from __future__ import annotations

import httpx
import pytest

from core.core.exceptions import AiServiceUnavailableError
from core.features.ai.proxy import (
    build_forward_headers,
    forward_to_ai_agent,
    relay_response,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ai.test")


class TestBuildForwardHeaders:
    def test_only_authorization_and_slug_relayed(self) -> None:
        headers = build_forward_headers(authorization="Bearer abc", tenant_slug="acme")
        assert headers == {"Authorization": "Bearer abc", "X-Tenant-Slug": "acme"}

    def test_missing_pieces_omitted_not_empty(self) -> None:
        assert build_forward_headers(authorization=None, tenant_slug=None) == {}


class TestForwardToAiAgent:
    async def test_success_passes_through_status_and_body(self) -> None:
        seen: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            seen["slug"] = request.headers.get("x-tenant-slug")
            seen["path"] = request.url.path
            seen["body"] = request.content
            return httpx.Response(200, json={"data": [1]})

        response = await forward_to_ai_agent(
            _client(handler),
            method="POST",
            upstream_path="/ai/query",
            authorization="Bearer tok",
            tenant_slug="acme",
            body=b'{"q":"stock?"}',
        )

        assert response.status_code == 200
        assert seen["auth"] == "Bearer tok"
        assert seen["slug"] == "acme"
        assert seen["path"] == "/ai/query"
        assert seen["body"] == b'{"q":"stock?"}'

    async def test_upstream_error_status_is_returned_not_raised(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"type": "about:blank/ai-unavailable"})

        response = await forward_to_ai_agent(
            _client(handler),
            method="GET",
            upstream_path="/ai/suggestions",
            authorization="Bearer tok",
            tenant_slug="acme",
        )
        # Upstream application errors pass through untouched.
        assert response.status_code == 503

    async def test_query_params_are_forwarded(self) -> None:
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["status_q"] = request.url.params.get("status")
            return httpx.Response(200, json={"data": []})

        await forward_to_ai_agent(
            _client(handler),
            method="GET",
            upstream_path="/ai/anomalies",
            authorization="Bearer tok",
            tenant_slug="acme",
            params=[("status", "open")],
        )
        assert seen["status_q"] == "open"

    @pytest.mark.parametrize(
        ("transport_error",),
        [
            pytest.param(httpx.ConnectError("refused"), id="connect"),
            pytest.param(httpx.ReadTimeout("slow"), id="timeout"),
        ],
    )
    async def test_transport_failures_raise_typed_503(self, transport_error: Exception) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise transport_error

        with pytest.raises(AiServiceUnavailableError):
            await forward_to_ai_agent(
                _client(handler),
                method="GET",
                upstream_path="/ai/anomalies",
                authorization="Bearer tok",
                tenant_slug="acme",
            )

    async def test_no_auth_header_when_caller_sent_none(self) -> None:
        seen: dict[str, str | None] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            return httpx.Response(401)

        response = await forward_to_ai_agent(
            _client(handler),
            method="GET",
            upstream_path="/ai/suggestions",
            authorization=None,
            tenant_slug="acme",
        )
        assert response.status_code == 401
        assert seen["auth"] is None  # nothing fabricated upstream

    async def test_target_on_non_configured_host_is_refused(self) -> None:
        """An absolute upstream target escapes base_url — never relayed."""

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return httpx.Response(200)

        with pytest.raises(ValueError, match="non-configured host"):
            await forward_to_ai_agent(
                _client(handler),
                method="POST",
                upstream_path="http://evil.test/ai/suggestions/x/approve",
                authorization="Bearer tok",
                tenant_slug="acme",
            )


class TestRelayResponse:
    def test_status_body_and_content_type_carried(self) -> None:
        upstream = httpx.Response(
            422,
            json={"type": "https://problems/validation-error"},
            headers={"content-type": "application/problem+json"},
        )
        reply = relay_response(upstream)
        assert reply.status_code == 422
        assert b"validation-error" in reply.body
        assert reply.media_type == "application/problem+json"

    def test_missing_content_type_defaults_to_json(self) -> None:
        upstream = httpx.Response(200, content=b"{}")  # httpx sets json type; strip it
        upstream.headers.pop("content-type", None)
        reply = relay_response(upstream)
        assert reply.media_type == "application/json"
