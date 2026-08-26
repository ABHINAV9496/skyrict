"""LLM provider adapters and the settings-driven provider factory.

Public surface:
- :class:`LlmProvider` / ``LlmRequest`` / ``LlmCompletion`` (base protocol)
- :class:`OpenAiCompatibleProvider` (the one HTTP dialect adapter)
- :func:`build_providers_from_settings` (startup factory, fail-fast)
"""

from __future__ import annotations

from ai_agent.core.providers.base import LlmCompletion, LlmProvider, LlmRequest
from ai_agent.core.providers.openai_compatible import OpenAiCompatibleProvider
from ai_agent.core.providers.registry import (
    PROVIDER_PRESETS,
    build_provider,
    build_providers_from_settings,
    resolve_base_url,
)

__all__ = [
    "PROVIDER_PRESETS",
    "LlmCompletion",
    "LlmProvider",
    "LlmRequest",
    "OpenAiCompatibleProvider",
    "build_provider",
    "build_providers_from_settings",
    "resolve_base_url",
]
