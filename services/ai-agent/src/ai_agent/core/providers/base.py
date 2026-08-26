"""Provider-agnostic LLM abstraction - protocol and value types.

The AI agent never talks to a vendor SDK: every provider is an
:class:`LlmProvider` speaking one of two dialects (today only OpenAI-compatible
HTTP; SKY-59 may add more). Engines depend ONLY on this protocol, so providers
are swappable via configuration without touching business code.

Security invariants every implementation MUST keep:

- API keys travel in Authorization headers only and are NEVER logged,
  returned in results, or embedded in exceptions.
- Exceptions carry sanitized, client-safe detail strings (failure MODE, not
  provider internals).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class LlmRequest:
    """One generation request, already engine-sanitized.

    Prompts carry tenant DATA (product names, quantities) - residency rules
    decide which providers may see them (``require_local_only`` routing).
    """

    system_prompt: str
    user_prompt: str
    max_tokens: int = 512
    temperature: float = 0.2


@dataclass(frozen=True, slots=True)
class LlmCompletion:
    """A successful generation with its provenance for audit trails."""

    text: str
    model_used: str
    latency_ms: int


@runtime_checkable
class LlmProvider(Protocol):
    """Structural contract satisfied by every provider adapter."""

    name: str
    model: str
    local_only: bool

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        """Return one completion or raise a typed AI error."""
        ...
