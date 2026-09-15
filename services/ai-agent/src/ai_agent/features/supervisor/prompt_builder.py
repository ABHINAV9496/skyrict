"""Stable-prefix prompt builder - keep leading system-prompt bytes cacheable.

Provider KV caches (Ollama prefix sharing, OpenAI prompt caching) are only
effective when the leading tokens of a request are byte-identical across
calls. The supervisor assembles a static persona prefix plus per-turn dynamic
blocks; this builder enforces that the dynamic block is always *appended after*
the stable prefix (never inserted before or inside it), so the leading bytes
stay byte-identical and the provider cache stays hot.

The builder also emits telemetry on prefix reuse so we can observe how often
each route reuses its stable prefix in production (a reused prefix means the
provider KV cache can serve the leading tokens without recomputation).
"""

from __future__ import annotations

import structlog

from ai_agent.core.providers import LlmRequest

logger = structlog.get_logger("ai_agent.prompt_builder")

# Per-route reuse counters, keyed by route label. Reset on process restart and
# per worker; that is fine for telemetry (approximate, monotonic per process).
_PREFIX_REUSES: dict[str, int] = {}


class StablePromptBuilder:
    """Construct :class:`LlmRequest` objects with a byte-stable system prefix.

    Parameters:
        prefix: static leading section of the system prompt (persona/instructions)
            that is byte-identical across every request built by this instance.
        route: telemetry label, e.g. ``"classify"`` or ``"supervisor_answer"``.

    ``build()`` returns an :class:`LlmRequest` whose ``system_prompt`` is
    ``prefix`` (when ``system_tail`` is empty) or
    ``prefix + "\\n\\n" + system_tail`` - the dynamic tail is always appended
    after the prefix, never prepended, so the leading bytes of ``system_prompt``
    are identical for every request this builder produces.
    """

    def __init__(self, *, prefix: str, route: str) -> None:
        self._prefix = prefix
        self._route = route

    @property
    def reuse_count(self) -> int:
        """Number of times this process has built with this route's prefix."""
        return _PREFIX_REUSES.get(self._route, 0)

    def build(
        self,
        *,
        user_prompt: str,
        system_tail: str = "",
        max_tokens: int = 512,
        temperature: float = 0.2,
        think: bool | None = None,
        json_mode: bool = False,
        image_blocks: list[dict[str, object]] | None = None,
    ) -> LlmRequest:
        """Build an :class:`LlmRequest` with the stable prefix first.

        ``system_tail`` (e.g. conversation history, live CRM/finance data) is
        appended after the prefix. Callers that budget-trim their dynamic tail
        should trim exactly as before and pass the resulting string here; the
        builder never reorders or rewrites it, so under-budget prompts stay
        byte-identical to the pre-builder formatting.
        """
        system_prompt = f"{self._prefix}\n\n{system_tail}" if system_tail else self._prefix
        _PREFIX_REUSES[self._route] = _PREFIX_REUSES.get(self._route, 0) + 1
        reuse_count = _PREFIX_REUSES[self._route]
        if reuse_count > 1:
            logger.info(
                "prompt.prefix_reuse",
                route=self._route,
                reuse_count=reuse_count,
                prefix_chars=len(self._prefix),
            )
        return LlmRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            think=think,
            json_mode=json_mode,
            image_blocks=image_blocks,
        )
