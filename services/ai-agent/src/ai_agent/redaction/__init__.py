"""PII redaction package (HR-AI-001, Commit 1).

The redaction pipeline is the **prereq gate** for every AI feature that talks
to an LLM. It strips/masks names, IDs, bank fragments, and salaries from any
free text BEFORE the text reaches a provider, so a raw sensitive value can
never leave the service.

The gate is applied inside :class:`ai_agent.core.llm_router.LlmRouter` to every
outbound ``LlmRequest`` (system + user prompt) before any provider adapter
serializes the payload. Because the router is the ONLY path to an LLM in
ai-agent, one injection point gates every provider call.

Design rules:

- **Fail closed.** Anything that matches a sensitive pattern is masked by a
  unique token. The original value is never preserved in the returned text.
- **Deterministic.** Same input always yields the same output, so the corpus
  tests and any downstream assertions are stable.
- **Pure.** No I/O; trivially unit-testable without a database or network.
"""

from __future__ import annotations

from ai_agent.redaction.pipeline import RedactionResult, Redactor, redact_text

__all__ = ["RedactionResult", "Redactor", "redact_text"]
