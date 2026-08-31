"""OpenAI-compatible chat-completions adapter (raw httpx, no vendor SDK).

Speaks ``POST {base_url}/chat/completions`` - the de-facto standard dialect
shared by OpenAI, OpenRouter, Groq, OmniRoute, AgentRouter and self-hosted
gateways. One adapter therefore serves every preset in the registry.

Error mapping (the router relies on this distinction):

- transport failure, timeout, or any HTTP error status -> AiUnavailableError
  ("this provider could not serve the request" - try the next one);
- HTTP 200 with a body that fails schema validation -> AiInvalidResponseError
  ("the provider answered but unusably").

API keys are sent as Bearer headers and never appear in logs, results, or
exception strings.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

import httpx
import structlog

from ai_agent.core.exceptions import AiInvalidResponseError, AiUnavailableError
from ai_agent.core.providers.base import LlmCompletion, LlmRequest, LlmStreamChunk

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger("ai_agent.providers")

# The only JSON paths we read; anything missing/mistyped is a 502, not a crash.
_MIN_TIMEOUT_SECONDS = 1.0


class OpenAiCompatibleProvider:
    """One configured provider endpoint speaking the OpenAI-compatible dialect."""

    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key: str,
        local_only: bool,
        timeout_seconds: float,
    ) -> None:
        if not model.strip():
            raise ValueError("model is required")
        if not base_url.strip().lower().startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self.name = name
        self.model = model
        self.local_only = local_only
        self._base_url = base_url.rstrip("/")
        # Empty key allowed: some local gateways need no auth. Never logged.
        self._api_key = api_key
        self._timeout_seconds = max(timeout_seconds, _MIN_TIMEOUT_SECONDS)

    def _create_client(self) -> httpx.AsyncClient:
        """Create the per-call HTTP client (overridable seam for tests)."""
        return httpx.AsyncClient(timeout=self._timeout_seconds)

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        """POST one chat completion and parse choices[0].message.content."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        started = time.perf_counter()
        try:
            async with self._create_client() as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "provider.http_error",
                provider=self.name,
                status_code=exc.response.status_code,
            )
            raise AiUnavailableError(f"Provider '{self.name}' could not serve the request") from exc
        except httpx.HTTPError as exc:
            # TimeoutException, ConnectError, and every other transport issue.
            logger.warning("provider.transport_error", provider=self.name)
            raise AiUnavailableError(f"Provider '{self.name}' is unreachable") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        text, model_used = _parse_completion_payload(response)
        return LlmCompletion(text=text, model_used=model_used, latency_ms=latency_ms)

    async def stream(
        self,
        request: LlmRequest,
    ) -> AsyncIterator[LlmStreamChunk]:
        """POST a streaming chat completion and yield token deltas (SKY-60).

        Uses ``stream: true`` and parses ``data:`` SSE frames as they arrive
        - the response is NEVER buffered whole. The http client lives for the
        generator's lifetime: when the consumer stops iterating or closes the
        iterator (client disconnect), the ``async with`` exits and the
        upstream request is cancelled (disconnect propagation).

        Error mapping matches :meth:`complete`:

        - transport failure, timeout, or any HTTP error status ->
          :class:`AiUnavailableError`;
        - a frame whose schema fails validation ->
          :class:`AiInvalidResponseError`.

        Both are raised on iteration; a pre-yield failure lets the router
        fail over, a post-yield failure surfaces mid-stream.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            async with (
                self._create_client() as client,
                client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response,
            ):
                if response.status_code >= 400:
                    logger.warning(
                        "provider.stream_http_error",
                        provider=self.name,
                        status_code=response.status_code,
                    )
                    raise AiUnavailableError(f"Provider '{self.name}' could not serve the request")
                model_used = ""
                async for line in response.aiter_lines():
                    text_frame = _parse_stream_frame(line)
                    if text_frame is None:
                        continue
                    delta, frame_model = text_frame
                    if delta or frame_model:
                        model_used = frame_model or model_used
                        if delta:
                            yield LlmStreamChunk(
                                token_delta=delta,
                                model_used=model_used,
                            )
        except httpx.HTTPError as exc:
            # Connect/timeout/etc. - the provider never served the request.
            logger.warning("provider.stream_transport_error", provider=self.name)
            raise AiUnavailableError(f"Provider '{self.name}' is unreachable") from exc


def _parse_stream_frame(line: str) -> tuple[str, str] | None:
    """Parse one SSE ``data:`` frame into (token_delta, model) or None.

    Returns None for keep-alive/schema-less frames every streaming API sends;
    raises :class:`AiInvalidResponseError` for a data frame whose schema is
    unusable (the provider "answered but unusably" - 502 semantics).
    """
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        frame = json.loads(payload)
        choices = frame.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
        content = delta.get("content") if isinstance(delta, dict) else None
        if content is not None and not isinstance(content, str):
            raise TypeError("delta content must be a string")
        model = frame.get("model")
        if model is not None and not isinstance(model, str):
            raise TypeError("model must be a string")
    except (ValueError, TypeError) as exc:
        logger.warning("provider.invalid_stream_schema")
        raise AiInvalidResponseError(
            "Provider returned a stream frame that failed schema validation"
        ) from exc
    return (content or "", model or "")


def _parse_completion_payload(response: httpx.Response) -> tuple[str, str]:
    """Extract (text, model) from a 200 body; schema failures are 502s."""
    try:
        data = response.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
        model = data.get("model") or ""
        if not isinstance(content, str) or not isinstance(model, str):
            raise TypeError("content/model must be strings")
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning("provider.invalid_response_schema")
        raise AiInvalidResponseError(
            "Provider returned a response that failed schema validation"
        ) from exc
    return content, model
