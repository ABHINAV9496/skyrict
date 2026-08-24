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

import time
from typing import Any

import httpx
import structlog

from ai_agent.core.exceptions import AiInvalidResponseError, AiUnavailableError
from ai_agent.core.providers.base import LlmCompletion, LlmRequest

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
