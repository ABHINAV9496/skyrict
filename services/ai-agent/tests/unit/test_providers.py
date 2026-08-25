"""Unit tests for the OpenAI-compatible adapter and the provider registry.

The adapter is exercised over ``httpx.MockTransport`` - real HTTP semantics,
no network. Security assertions: the API key travels ONLY in the Authorization
header and never leaks into results, logs, or exception strings.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ai_agent.core.exceptions import AiInvalidResponseError, AiUnavailableError, StartupError
from ai_agent.core.providers import LlmRequest, OpenAiCompatibleProvider
from ai_agent.core.providers.registry import (
    build_provider,
    build_providers_from_settings,
    resolve_base_url,
)


def _make_provider(
    handler: Any,
    *,
    api_key: str = "sk-secret-key",
    local_only: bool = False,
) -> tuple[OpenAiCompatibleProvider, list[httpx.Request]]:
    """Build a provider wired to a MockTransport; capture outbound requests."""
    seen: list[httpx.Request] = []

    def _transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    provider = OpenAiCompatibleProvider(
        name="testprovider",
        model="test-model-1",
        base_url="https://api.test.example/v1",
        api_key=api_key,
        local_only=local_only,
        timeout_seconds=5,
    )
    # Swap the client factory for one bound to the mock transport (the
    # production path constructs a real client per call).
    provider._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5,
        transport=httpx.MockTransport(_transport_handler),
    )
    return provider, seen


_REQUEST = LlmRequest(system_prompt="be terse", user_prompt="say hi")


class TestOpenAiCompatibleProvider:
    async def test_successful_completion(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"role": "assistant", "content": "hi there"}}],
                    "model": "test-model-1",
                },
            )

        provider, _ = _make_provider(handler)
        completion = await provider.complete(_REQUEST)

        assert completion.text == "hi there"
        assert completion.model_used == "test-model-1"
        assert completion.latency_ms >= 0

    async def test_request_shape_and_auth_header(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("Authorization")
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "ok"}}], "model": "m"},
            )

        provider, _ = _make_provider(handler)
        await provider.complete(_REQUEST)

        assert captured["auth"] == "Bearer sk-secret-key"
        body = captured["body"]
        assert body["model"] == "test-model-1"
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][0]["content"] == "be terse"
        assert body["messages"][1]["content"] == "say hi"

    async def test_http_error_maps_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "overloaded"})

        provider, _ = _make_provider(handler)
        with pytest.raises(AiUnavailableError):
            await provider.complete(_REQUEST)

    async def test_timeout_maps_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        provider, _ = _make_provider(handler)
        with pytest.raises(AiUnavailableError):
            await provider.complete(_REQUEST)

    async def test_malformed_json_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not-json{{{")

        provider, _ = _make_provider(handler)
        with pytest.raises(AiInvalidResponseError):
            await provider.complete(_REQUEST)

    async def test_missing_choices_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"object": "chat.completion"})

        provider, _ = _make_provider(handler)
        with pytest.raises(AiInvalidResponseError):
            await provider.complete(_REQUEST)

    async def test_non_string_content_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": 42}}]})

        provider, _ = _make_provider(handler)
        with pytest.raises(AiInvalidResponseError):
            await provider.complete(_REQUEST)

    async def test_api_key_never_in_error_messages(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        provider, _ = _make_provider(handler)
        with pytest.raises(AiUnavailableError) as exc_info:
            await provider.complete(_REQUEST)
        assert "sk-secret-key" not in str(exc_info.value)


class TestRegistryFactory:
    def test_preset_resolved_without_override(self) -> None:
        assert resolve_base_url("openrouter", "") == "https://openrouter.ai/api/v1"

    def test_override_wins_over_preset(self) -> None:
        assert resolve_base_url("groq", "https://mirror.example/v1") == "https://mirror.example/v1"

    def test_unknown_key_rejected_at_build(self) -> None:
        with pytest.raises(StartupError, match="Unknown AI provider"):
            build_provider(
                provider_key="ollama",
                model="llama3",
                timeout_seconds=5,
            )

    def test_presetless_key_requires_base_url(self) -> None:
        with pytest.raises(StartupError, match="base URL"):
            build_provider(provider_key="omniroute", model="m", timeout_seconds=5)

    def test_settings_with_no_providers_builds_empty_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.delenv("AI_FALLBACK_PROVIDER", raising=False)
        from ai_agent.core.config import Settings

        config = Settings(_env_file=None)  # type: ignore[call-arg]
        assert build_providers_from_settings(config) == []

    def test_primary_plus_fallback_built_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AI_PROVIDER", "openrouter")
        monkeypatch.setenv("AI_MODEL", "org/model-a")
        monkeypatch.setenv("AI_API_KEY", "key-a")
        monkeypatch.setenv("AI_FALLBACK_PROVIDER", "omniroute")
        monkeypatch.setenv("AI_FALLBACK_MODEL", "model-b")
        monkeypatch.setenv("AI_FALLBACK_BASE_URL", "https://gateway.internal/v1")
        from ai_agent.core.config import Settings

        config = Settings(_env_file=None)  # type: ignore[call-arg]
        providers = build_providers_from_settings(config)

        assert [p.name for p in providers] == ["openrouter", "omniroute"]
        assert providers[0].local_only is False
