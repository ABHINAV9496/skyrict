"""Embedding provider adapters (SKY-58) - OpenAI-compatible ``/embeddings``.

One adapter class serves every OpenAI-compatible embedding endpoint, mirroring
the LLM provider philosophy in ``core/providers``:

- ``openai`` - ``text-embedding-3-small`` via the OpenAI API with Matryoshka
  dimension reduction, or ANY OpenAI-compatible endpoint by overriding the
  base URL (e.g. Gemini's ``gemini-embedding-2``). ``"dimensions"`` is sent
  in the payload and these providers honor it.
- ``ollama`` - local ``nomic-embed-text`` via ``http://host:11434/v1``. It
  emits 768-dim vectors natively and does NOT accept the ``dimensions``
  payload key, so ``send_dimensions`` is False and the key is omitted.

All supported providers emit 768-dim vectors matching the ``Vector(768)``
columns (``ai_rag_chunks.embedding`` / ``ai_inv_item_embeddings.embedding``),
so switching provider is a one-variable config change (migration 0013).

Security invariants mirror ``core/providers/base``: API keys travel in
Authorization headers only and NEVER appear in logs, results, or exception
strings. Transport/HTTP failures map to :class:`AiUnavailableError`, schema
failures (including dimension mismatch) to :class:`AiInvalidResponseError`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx
import structlog

from ai_agent.core.exceptions import AiInvalidResponseError, AiUnavailableError, StartupError

if TYPE_CHECKING:
    from ai_agent.core.config import Settings

logger = structlog.get_logger("ai_agent.embeddings")

_MIN_TIMEOUT_SECONDS = 1.0

# Known provider keys and their default OpenAI-compatible base URLs.
EMBEDDING_KEYS = frozenset({"openai", "ollama"})
EMBEDDING_PRESETS: dict[str, str] = {"openai": "https://api.openai.com/v1"}

# Length of the vector column in ai_rag_chunks / ai_inv_item_embeddings - the
# adapter enforces it so a mismatched provider fails fast instead of
# corrupting the index. Every supported provider emits this many dimensions.
_INDEX_DIMENSIONS = 768


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """Successful embedding batch with provenance for audit logs."""

    vectors: list[list[float]]
    model_used: str
    dims: int
    latency_ms: int


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Structural contract satisfied by every embedding adapter."""

    name: str
    model: str
    dims: int

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed *texts* (a batch) or raise a typed AI error."""
        ...


class OpenAiCompatibleEmbeddingProvider:
    """One configured endpoint speaking the OpenAI ``/embeddings`` dialect.

    Args:
        name: Provider key (``openai``, ``ollama``, ...) for logs.
        model: Embedding model identifier.
        base_url: API base URL (without the ``/embeddings`` suffix).
        api_key: Bearer key; empty for keyless local endpoints. Never logged.
        dims: Expected output dimension count (matches the vector column).
        batch_size: Max texts per HTTP request.
        timeout_seconds: Per-request timeout (floored at 1s).
        send_dimensions: Whether the provider honors the OpenAI ``dimensions``
            payload key (Matryoshka reduction). True for openai/Gemini, False
            for ollama which rejects unknown fields.
    """

    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key: str,
        dims: int,
        batch_size: int,
        timeout_seconds: float,
        send_dimensions: bool = False,
    ) -> None:
        if not model.strip():
            raise ValueError("model is required")
        if not base_url.strip().lower().startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        if dims <= 0:
            raise ValueError("dims must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self.name = name
        self.model = model
        self.dims = dims
        self._base_url = base_url.rstrip("/")
        # Empty key allowed: some local endpoints need no auth. Never logged.
        self._api_key = api_key
        self.send_dimensions = send_dimensions
        self._batch_size = batch_size
        self._timeout_seconds = max(timeout_seconds, _MIN_TIMEOUT_SECONDS)

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=self._timeout_seconds)

    async def embed(self, texts: list[str]) -> EmbeddingResult:
        """Embed a batch; empty input returns immediately with no network."""
        if not texts:
            return EmbeddingResult(vectors=[], model_used=self.model, dims=self.dims, latency_ms=0)

        started = time.perf_counter()
        vectors: list[list[float]] = []
        model_used = self.model
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            batch_vectors, model_used = await self._embed_batch(batch)
            vectors.extend(batch_vectors)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return EmbeddingResult(
            vectors=vectors, model_used=model_used, dims=self.dims, latency_ms=latency_ms
        )

    async def _embed_batch(self, texts: list[str]) -> tuple[list[list[float]], str]:
        payload: dict[str, object] = {"model": self.model, "input": texts}
        if self.send_dimensions:
            payload["dimensions"] = self.dims
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            async with self._create_client() as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "embedding.http_error",
                provider=self.name,
                status_code=exc.response.status_code,
            )
            raise AiUnavailableError(
                f"Embedding provider '{self.name}' could not serve the request"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("embedding.transport_error", provider=self.name)
            raise AiUnavailableError(f"Embedding provider '{self.name}' is unreachable") from exc

        vectors, model = self._parse_embedding_payload(response, expected=len(texts))
        if any(len(v) != self.dims for v in vectors):
            logger.warning(
                "embedding.dimension_mismatch",
                provider=self.name,
                expected=self.dims,
                got=len(vectors[0]) if vectors else 0,
            )
            raise AiInvalidResponseError(
                "Embedding provider returned vectors of the wrong dimension"
            )
        return vectors, model

    @staticmethod
    def _parse_embedding_payload(
        response: httpx.Response, *, expected: int
    ) -> tuple[list[list[float]], str]:
        """Extract (vectors, model) from a 200 body; schema failures are 502s."""
        try:
            data = response.json()
            raw = data["data"]
            if not isinstance(raw, list):
                raise TypeError("data must be a list")
            ordered = sorted(enumerate(raw), key=lambda pair: int(pair[1].get("index", pair[0])))
            vectors = [item["embedding"] for _, item in ordered]
            model = data.get("model") or ""
            if not all(isinstance(v, list) for v in vectors):
                raise TypeError("embedding must be a list")
            if any(not all(isinstance(x, (int, float)) for x in v) for v in vectors):
                raise TypeError("embedding values must be numbers")
            if model and not isinstance(model, str):
                raise TypeError("model must be a string")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("embedding.invalid_response_schema")
            raise AiInvalidResponseError(
                "Embedding provider returned a response that failed schema validation"
            ) from exc

        if len(vectors) != expected:
            logger.warning("embedding.count_mismatch", expected=expected, got=len(vectors))
            raise AiInvalidResponseError(
                "Embedding provider returned a different number of vectors than requested"
            )
        return vectors, model


def build_embedding_provider(config: Settings) -> EmbeddingProvider | None:
    """Build the configured embedding provider, or None when disabled.

    Raises:
        StartupError: On an unknown provider key, a missing required key
            (openai), or a missing base URL (ollama).
    """
    raw_key = config.EMBEDDING_PROVIDER
    if raw_key is None:
        return None
    key = raw_key.strip().lower()
    if key not in EMBEDDING_KEYS:
        raise StartupError(
            f"Unknown embedding provider '{raw_key}' - expected one of {sorted(EMBEDDING_KEYS)}"
        )

    base_url = (config.EMBEDDING_BASE_URL or "").strip() or EMBEDDING_PRESETS.get(key, "")
    if not base_url:
        raise StartupError(f"AI_EMBEDDING_BASE_URL is required for embedding provider '{key}'")
    if key == "openai" and not config.EMBEDDING_API_KEY:
        raise StartupError("AI_EMBEDDING_API_KEY is required for the 'openai' embedding provider")

    # Every supported provider emits _INDEX_DIMENSIONS-dim vectors matching the
    # Vector(_INDEX_DIMENSIONS) columns. Fail fast on mismatch so a misconfigured
    # provider surfaces at boot instead of at the database layer.
    if config.EMBEDDING_DIMENSIONS != _INDEX_DIMENSIONS:
        raise StartupError(
            f"AI_EMBEDDING_DIMENSIONS must match the vector columns dimension ({_INDEX_DIMENSIONS})"
        )

    return OpenAiCompatibleEmbeddingProvider(
        name=key,
        model=config.EMBEDDING_MODEL,
        base_url=base_url,
        api_key=config.EMBEDDING_API_KEY or "",
        dims=config.EMBEDDING_DIMENSIONS,
        batch_size=config.EMBEDDING_BATCH_SIZE,
        timeout_seconds=config.EMBEDDING_TIMEOUT_SECONDS,
        # Only providers honoring Matryoshka reduction (openai itself, and
        # Gemini via the base-URL override) accept the dimensions key; ollama
        # rejects unknown fields so it is omitted for key == "ollama".
        send_dimensions=key == "openai",
    )
