"""Unit tests for the OpenAI-compatible embedding adapter and factory.

Exercised over ``httpx.MockTransport`` — real HTTP semantics, no network.
Security assertions: the API key travels ONLY in the Authorization header and
never leaks into results, logs, or exception strings.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from ai_agent.core.embedding import (
    EmbeddingResult,
    OpenAiCompatibleEmbeddingProvider,
    build_embedding_provider,
)
from ai_agent.core.exceptions import AiInvalidResponseError, AiUnavailableError, StartupError

_DIMS = 4


def _make_provider(
    handler: Any,
    *,
    api_key: str = "sk-embed-secret",
    dims: int = _DIMS,
    batch_size: int = 2,
    name: str = "openai",
    send_dimensions: bool = True,
) -> tuple[OpenAiCompatibleEmbeddingProvider, list[httpx.Request]]:
    """Build a provider wired to a MockTransport; capture outbound requests."""
    seen: list[httpx.Request] = []

    def _transport_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    provider = OpenAiCompatibleEmbeddingProvider(
        name=name,
        model="text-embedding-3-small",
        base_url="https://api.openai.com/v1",
        api_key=api_key,
        dims=dims,
        batch_size=batch_size,
        timeout_seconds=5,
        send_dimensions=send_dimensions,
    )
    provider._create_client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        timeout=5,
        transport=httpx.MockTransport(_transport_handler),
    )
    return provider, seen


def _embedding_body(
    count: int, dims: int = _DIMS, model: str = "text-embedding-3-small"
) -> dict[str, Any]:
    return {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": i, "embedding": [float(i) * 0.1] * dims}
            for i in range(count)
        ],
    }


class TestOpenAiCompatibleEmbeddingProvider:
    async def test_successful_embedding(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_embedding_body(2))

        provider, _ = _make_provider(handler)
        result = await provider.embed(["hello", "world"])

        assert isinstance(result, EmbeddingResult)
        assert len(result.vectors) == 2
        assert all(len(v) == _DIMS for v in result.vectors)
        assert result.model_used == "text-embedding-3-small"
        assert result.dims == _DIMS
        assert result.latency_ms >= 0

    async def test_request_shape_and_auth_header(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("Authorization")
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_embedding_body(2))

        provider, _ = _make_provider(handler)
        await provider.embed(["hello", "world"])

        assert captured["auth"] == "Bearer sk-embed-secret"
        assert captured["url"] == "https://api.openai.com/v1/embeddings"
        body = captured["body"]
        assert body["model"] == "text-embedding-3-small"
        assert body["input"] == ["hello", "world"]
        assert body["dimensions"] == _DIMS

    async def test_send_dimensions_false_omits_dimensions_key(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_embedding_body(2))

        # ollama (name="ollama", send_dimensions=False) never sends the key.
        provider, _ = _make_provider(handler, name="ollama", send_dimensions=False)
        await provider.embed(["hello", "world"])

        assert "dimensions" not in captured["body"]

    async def test_batches_requests_at_batch_size_boundary(self) -> None:
        requests_seen: list[list[str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            inputs = body["input"]
            requests_seen.append(inputs)
            return httpx.Response(200, json=_embedding_body(len(inputs), dims=_DIMS))

        provider, _ = _make_provider(handler, batch_size=2)
        result = await provider.embed(["a", "b", "c"])

        assert requests_seen == [["a", "b"], ["c"]]
        # The fake body emits vectors [i*0.1]*dims per request-local index;
        # concat order matches the flattened input order with no gaps.
        assert [round(v[0], 1) for v in result.vectors] == [0.0, 0.1, 0.0]

    async def test_empty_input_returns_immediately_without_network(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("no network on empty batch")

        provider, seen = _make_provider(handler)
        result = await provider.embed([])

        assert result.vectors == []
        assert seen == []
        assert result.dims == _DIMS

    async def test_out_of_order_indices_are_sorted_by_index(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = _embedding_body(2)  # data[0]=index 0 vec[0.0], data[1]=index 1 vec[0.1]
            body["data"][0]["index"], body["data"][1]["index"] = 1, 0
            return httpx.Response(200, json=body)

        provider, _ = _make_provider(handler)
        result = await provider.embed(["first", "second"])

        # Sorted by index: the 0.1 vector (originally at slot 1) is emitted
        # first, so "first" receives it.
        assert result.vectors[0][0] == 0.1
        assert result.vectors[1][0] == 0.0

    async def test_http_error_maps_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"})

        provider, _ = _make_provider(handler)
        with pytest.raises(AiUnavailableError):
            await provider.embed(["hello"])

    async def test_timeout_maps_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        provider, _ = _make_provider(handler)
        with pytest.raises(AiUnavailableError):
            await provider.embed(["hello"])

    async def test_malformed_json_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not-json{{{")

        provider, _ = _make_provider(handler)
        with pytest.raises(AiInvalidResponseError):
            await provider.embed(["hello"])

    async def test_missing_data_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"object": "list", "model": "m"})

        provider, _ = _make_provider(handler)
        with pytest.raises(AiInvalidResponseError):
            await provider.embed(["hello"])

    async def test_wrong_vector_count_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_embedding_body(1))

        provider, _ = _make_provider(handler)
        with pytest.raises(AiInvalidResponseError):
            await provider.embed(["a", "b"])

    async def test_wrong_dimension_maps_to_invalid_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_embedding_body(1, dims=8))

        provider, _ = _make_provider(handler, dims=_DIMS)
        with pytest.raises(AiInvalidResponseError):
            await provider.embed(["a"])

    async def test_api_key_never_in_error_messages(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        provider, _ = _make_provider(handler)
        with pytest.raises(AiUnavailableError) as exc_info:
            await provider.embed(["hello"])
        assert "sk-embed-secret" not in str(exc_info.value)


class TestBuildEmbeddingProvider:
    def _settings(self, monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
        monkeypatch.delenv("AI_EMBEDDING_PROVIDER", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(f"AI_{key}", value)
        from ai_agent.core.config import Settings

        return Settings(_env_file=None)  # type: ignore[call-arg]

    def test_unset_provider_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(monkeypatch)
        assert build_embedding_provider(config) is None

    def test_openai_requires_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(monkeypatch, EMBEDDING_PROVIDER="openai")
        with pytest.raises(StartupError, match="API_KEY"):
            build_embedding_provider(config)

    def test_unknown_provider_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(
            monkeypatch,
            EMBEDDING_PROVIDER="voyage",
            EMBEDDING_API_KEY="k",
        )
        with pytest.raises(StartupError, match="Unknown embedding provider"):
            build_embedding_provider(config)

    def test_openai_builds_with_preset_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(
            monkeypatch,
            EMBEDDING_PROVIDER="openai",
            EMBEDDING_API_KEY="sk-123",
        )
        provider = build_embedding_provider(config)
        assert provider is not None
        assert provider.name == "openai"
        assert provider.dims == 768
        assert provider.send_dimensions is True

    def test_dimension_mismatch_rejected_for_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(
            monkeypatch,
            EMBEDDING_PROVIDER="openai",
            EMBEDDING_API_KEY="sk-123",
            EMBEDDING_DIMENSIONS="512",
        )
        with pytest.raises(StartupError, match="must match"):
            build_embedding_provider(config)

    def test_ollama_requires_explicit_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(
            monkeypatch,
            EMBEDDING_PROVIDER="ollama",
            EMBEDDING_API_KEY="",
        )
        with pytest.raises(StartupError, match="BASE_URL"):
            build_embedding_provider(config)

    def test_ollama_builds_with_local_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(
            monkeypatch,
            EMBEDDING_PROVIDER="ollama",
            EMBEDDING_API_KEY="",
            EMBEDDING_MODEL="nomic-embed-text",
            EMBEDDING_BASE_URL="http://localhost:11434/v1",
        )
        provider = build_embedding_provider(config)
        assert provider is not None
        assert provider.name == "ollama"
        assert provider.model == "nomic-embed-text"
        assert provider.dims == 768
        assert provider.send_dimensions is False

    def test_ollama_dimension_mismatch_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = self._settings(
            monkeypatch,
            EMBEDDING_PROVIDER="ollama",
            EMBEDDING_API_KEY="",
            EMBEDDING_MODEL="nomic-embed-text",
            EMBEDDING_BASE_URL="http://localhost:11434/v1",
            EMBEDDING_DIMENSIONS="512",
        )
        with pytest.raises(StartupError, match="must match"):
            build_embedding_provider(config)
