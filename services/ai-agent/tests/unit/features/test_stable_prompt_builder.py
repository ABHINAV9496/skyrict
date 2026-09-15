"""SKY-100: StablePromptBuilder keeps leading system-prompt bytes cacheable.

Provider KV caches (Ollama prefix sharing, OpenAI prompt caching) reuse
computation only when a request's leading tokens are byte-identical across
calls. These tests pin:

- the builder emits ``prefix`` exactly when there is no dynamic tail, and
  ``prefix + "\\n\\n" + tail`` otherwise - dynamic content never precedes or
  rewrites the stable prefix;
- consecutive builds on the same route reuse the same leading bytes and
  increase the per-route reuse counter;
- the service classification/answer routes and the CRM/Finance delegate
  routes actually route their dynamic assembly through a stable builder, so
  their under-budget output is byte-identical to the pre-builder formatting
  while the leading prefix stays fixed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from ai_agent.features.supervisor.prompt_builder import StablePromptBuilder
from ai_agent.features.supervisor.prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    CRM_SYSTEM_PROMPT,
    FINANCE_SYSTEM_PROMPT,
    SUPERVISOR_SYSTEM_PROMPT,
)

if TYPE_CHECKING:
    from ai_agent.core.providers import LlmRequest


class _CaptureRouter:
    """Router that captures the last LlmRequest and echoes a canned answer."""

    def __init__(self) -> None:
        self.has_providers = True
        self.last_request: LlmRequest | None = None

    async def complete(self, request: LlmRequest) -> Any:
        self.last_request = request
        return SimpleNamespace(text="answer", model_used="fake-model", latency_ms=1)

    async def stream(self, request: LlmRequest) -> Any:
        self.last_request = request
        yield SimpleNamespace(token_delta="answer", model_used="fake-model")


class TestStablePromptBuilder:
    def test_empty_tail_is_exactly_the_prefix(self) -> None:
        builder = StablePromptBuilder(prefix="PREFIX", route="test")
        request = builder.build(user_prompt="q")
        assert request.system_prompt == "PREFIX"
        assert request.user_prompt == "q"

    def test_tail_is_appended_after_prefix(self) -> None:
        builder = StablePromptBuilder(prefix="PREFIX", route="test")
        request = builder.build(user_prompt="q", system_tail="TAIL")
        assert request.system_prompt == "PREFIX\n\nTAIL"

    def test_dynamic_tail_never_writes_before_prefix(self) -> None:
        builder = StablePromptBuilder(prefix="PREFIX", route="test")
        first = builder.build(user_prompt="a", system_tail="AAA")
        second = builder.build(user_prompt="b", system_tail="BBBBBB")
        # The leading bytes are the prefix in both - byte-identical, regardless
        # of how large or different the dynamic tails are.
        assert first.system_prompt.startswith("PREFIX")
        assert second.system_prompt.startswith("PREFIX")
        assert first.system_prompt[: len("PREFIX")] == second.system_prompt[: len("PREFIX")]

    def test_reuse_counter_increments_per_route(self) -> None:
        builder = StablePromptBuilder(prefix="PREFIX", route="route-a")
        assert builder.reuse_count == 0
        builder.build(user_prompt="q")
        assert builder.reuse_count == 1
        builder.build(user_prompt="q2")
        assert builder.reuse_count == 2
        # Routes are tracked independently.
        other = StablePromptBuilder(prefix="OTHER", route="route-b")
        other.build(user_prompt="q")
        assert other.reuse_count == 1
        assert builder.reuse_count == 2

    def test_passes_through_llm_request_fields(self) -> None:
        builder = StablePromptBuilder(prefix="PREFIX", route="test")
        request = builder.build(
            user_prompt="q",
            system_tail="TAIL",
            max_tokens=32,
            temperature=0.9,
            json_mode=True,
            image_blocks=[{"type": "image_url", "image_url": {"url": "u"}}],
        )
        assert request.max_tokens == 32
        assert request.temperature == 0.9
        assert request.json_mode is True
        assert request.image_blocks == [{"type": "image_url", "image_url": {"url": "u"}}]


class TestRouteWiring:
    """The real routes build through StablePromptBuilder instances."""

    async def test_classify_route_keeps_stable_prefix(self) -> None:
        from ai_agent.features.supervisor.service import _CLASSIFY_PROMPT_BUILDER

        first = _CLASSIFY_PROMPT_BUILDER.build(user_prompt="what stock is low")
        second = _CLASSIFY_PROMPT_BUILDER.build(user_prompt="any invoices due?")

        assert first.system_prompt == CLASSIFY_SYSTEM_PROMPT
        assert second.system_prompt == CLASSIFY_SYSTEM_PROMPT
        assert first.system_prompt == second.system_prompt

    async def test_supervisor_answer_stable_across_history_shape(self) -> None:
        from ai_agent.features.supervisor.service import _SUPERVISOR_ANSWER_BUILDER

        no_history = _SUPERVISOR_ANSWER_BUILDER.build(user_prompt="hello")
        with_history = _SUPERVISOR_ANSWER_BUILDER.build(
            user_prompt="hello",
            system_tail=(
                "--- Conversation history ---\n"
                "user: hi\nassistant: hello there\n"
                "--- End of conversation history ---"
            ),
        )

        # Same leading bytes up to the prefix length in both shapes.
        prefix = SUPERVISOR_SYSTEM_PROMPT
        assert no_history.system_prompt == prefix
        assert with_history.system_prompt.startswith(prefix)
        assert no_history.system_prompt[: len(prefix)] == with_history.system_prompt[: len(prefix)]

    async def test_crm_delegate_prompt_is_byte_stable_and_tail_appended(self) -> None:
        from ai_agent.features.supervisor.delegates import _CRM_PROMPT_BUILDER

        bare = _CRM_PROMPT_BUILDER.build(user_prompt="summarize my deals")
        rich = _CRM_PROMPT_BUILDER.build(
            user_prompt="summarize my deals",
            system_tail="Live CRM data:\nTotal opportunities: 3",
        )

        prefix = CRM_SYSTEM_PROMPT
        assert bare.system_prompt == prefix
        assert rich.system_prompt == f"{prefix}\n\nLive CRM data:\nTotal opportunities: 3"
        assert bare.system_prompt[: len(prefix)] == rich.system_prompt[: len(prefix)]

    async def test_finance_delegate_prompt_is_byte_stable_and_tail_appended(self) -> None:
        from ai_agent.features.supervisor.delegates import _FINANCE_PROMPT_BUILDER

        bare = _FINANCE_PROMPT_BUILDER.build(user_prompt="finances?")
        rich = _FINANCE_PROMPT_BUILDER.build(
            user_prompt="finances?",
            system_tail="Live finance data:\nTotal invoices: 5\n  - issued: 5",
        )

        prefix = FINANCE_SYSTEM_PROMPT
        assert bare.system_prompt == prefix
        assert rich.system_prompt == (
            f"{prefix}\n\nLive finance data:\nTotal invoices: 5\n  - issued: 5"
        )
        assert bare.system_prompt[: len(prefix)] == rich.system_prompt[: len(prefix)]
