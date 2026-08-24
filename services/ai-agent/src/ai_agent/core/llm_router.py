"""LLM router - ordered provider chain with typed failure semantics.

Executes one generation request across the configured providers in order
(primary first, then fallback). The router is the ONLY component engines may
use to reach an LLM, because it owns three cross-cutting contracts:

1. Fallback: a provider failing (unreachable / HTTP error) moves the request
   to the next provider transparently.
2. Typed errors after exhaustion (SKY-57 error contract):
   - every attempt unreachable/HTTP-failed            -> 503 AiUnavailableError
   - every attempt reached but returned garbage        -> 502 AiInvalidResponseError
   - mixed (some down, some garbage)                   -> 503 (the service
     genuinely could not complete; 502 would imply it tried and only got
     unusable answers)
   - no provider configured at all                     -> 503
3. Data residency: when a prompt carries local-only data
   (``require_local_only=True``), only providers flagged ``local_only`` are
   eligible; with none eligible the request fails closed as 422
   AiDataResidencyError BEFORE any data leaves.

Per-attempt failures are logged with the provider NAME and failure class only
- never keys, prompts, or response bodies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ai_agent.core.exceptions import (
    AiDataResidencyError,
    AiInvalidResponseError,
    AiUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_agent.core.providers.base import LlmCompletion, LlmProvider, LlmRequest

logger = structlog.get_logger("ai_agent.llm_router")


class LlmRouter:
    """Ordered failover across zero or more providers."""

    def __init__(self, providers: Sequence[LlmProvider]) -> None:
        self._providers: list[LlmProvider] = list(providers)

    @property
    def has_providers(self) -> bool:
        """False when no provider is configured - AI endpoints degrade to 503."""
        return bool(self._providers)

    @property
    def provider_count(self) -> int:
        """Number of configured providers (for startup logging/metrics)."""
        return len(self._providers)

    def has_local_only_clearance(self) -> bool:
        """True when at least one provider is cleared for local-only data."""
        return any(provider.local_only for provider in self._providers)

    async def complete(
        self,
        request: LlmRequest,
        *,
        require_local_only: bool = False,
    ) -> LlmCompletion:
        """Run ``request`` through the provider chain and return one completion.

        Raises:
            AiDataResidencyError: Local-only data but no cleared provider.
            AiUnavailableError: No eligible provider served the request.
            AiInvalidResponseError: All eligible providers answered unusably.
        """
        if require_local_only and not self.has_local_only_clearance():
            raise AiDataResidencyError()

        eligible = (
            [provider for provider in self._providers if provider.local_only]
            if require_local_only
            else self._providers
        )
        if not eligible:
            raise AiUnavailableError("No AI provider is configured")

        saw_unavailable = False
        for provider in eligible:
            try:
                completion = await provider.complete(request)
            except AiInvalidResponseError:
                logger.warning(
                    "llm_router.provider_invalid_response",
                    provider=provider.name,
                    model=provider.model,
                )
            except AiUnavailableError:
                saw_unavailable = True
                logger.warning(
                    "llm_router.provider_unavailable",
                    provider=provider.name,
                    model=provider.model,
                )
            else:
                logger.info(
                    "llm_router.completed",
                    provider=provider.name,
                    model_used=completion.model_used,
                    latency_ms=completion.latency_ms,
                )
                return completion

        if saw_unavailable:
            # At least one provider never answered at all - the service could
            # not complete the request, which outranks "answers were garbage".
            raise AiUnavailableError()
        # Every eligible provider answered, but none produced usable output.
        raise AiInvalidResponseError()
