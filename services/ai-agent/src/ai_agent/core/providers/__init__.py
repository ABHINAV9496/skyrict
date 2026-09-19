"""LLM provider adapters and the settings-driven provider factory.

Public surface:
- :class:`LlmProvider` / ``LlmRequest`` / ``LlmCompletion`` (base protocol)
- :class:`OpenAiCompatibleProvider` (the one HTTP dialect adapter)
- :class:`MockProvider` (deterministic in-process provider for tests/E2E)
- :func:`build_providers_from_settings` (startup factory, fail-fast)
"""

from __future__ import annotations

from ai_agent.core.providers.base import LlmCompletion, LlmProvider, LlmRequest
from ai_agent.core.providers.mock import MockBehavior, MockProvider
from ai_agent.core.providers.openai_compatible import OpenAiCompatibleProvider
from ai_agent.core.providers.registry import (
    NO_NETWORK_KEYS,
    PROVIDER_PRESETS,
    build_provider,
    build_providers_from_settings,
    resolve_base_url,
)

__all__ = [
    "NO_NETWORK_KEYS",
    "PROVIDER_PRESETS",
    "LlmCompletion",
    "LlmProvider",
    "LlmRequest",
    "MockBehavior",
    "MockProvider",
    "OpenAiCompatibleProvider",
    "build_provider",
    "build_providers_from_settings",
    "resolve_base_url",
]
