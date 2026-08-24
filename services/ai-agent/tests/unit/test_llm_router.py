"""Unit tests for the LLM router - fallback order and typed failure mapping."""

from __future__ import annotations

import pytest

from ai_agent.core.exceptions import (
    AiDataResidencyError,
    AiInvalidResponseError,
    AiUnavailableError,
)
from ai_agent.core.llm_router import LlmRouter
from ai_agent.core.providers.base import LlmCompletion, LlmRequest


class FakeProvider:
    """Scripted provider double: pops one outcome per complete() call.

    Outcomes are either exceptions (raised) or strings (returned as text).
    """

    def __init__(
        self,
        name: str,
        outcomes: list[Exception | str],
        *,
        model: str = "fake-model",
        local_only: bool = False,
    ) -> None:
        self.name = name
        self.model = model
        self.local_only = local_only
        self.outcomes = list(outcomes)
        self.calls = 0

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "unused-fallback-text"
        if isinstance(outcome, Exception):
            raise outcome
        return LlmCompletion(text=outcome, model_used=self.model, latency_ms=5)


_REQUEST = LlmRequest(system_prompt="s", user_prompt="u")


class TestHappyPath:
    async def test_primary_answered_first(self) -> None:
        primary = FakeProvider("primary", ["answer-a"])
        router = LlmRouter([primary])

        completion = await router.complete(_REQUEST)

        assert completion.text == "answer-a"
        assert primary.calls == 1

    async def test_fallback_used_when_primary_unavailable(self) -> None:
        primary = FakeProvider("primary", [AiUnavailableError("down")])
        fallback = FakeProvider("fallback", ["answer-b"])
        router = LlmRouter([primary, fallback])

        completion = await router.complete(_REQUEST)

        assert completion.text == "answer-b"
        assert primary.calls == 1
        assert fallback.calls == 1


class TestExhaustion:
    async def test_no_providers_configured(self) -> None:
        router = LlmRouter([])

        with pytest.raises(AiUnavailableError):
            await router.complete(_REQUEST)

    async def test_all_unavailable_maps_to_503(self) -> None:
        providers = [
            FakeProvider("a", [AiUnavailableError()]),
            FakeProvider("b", [AiUnavailableError()]),
        ]
        router = LlmRouter(providers)

        with pytest.raises(AiUnavailableError):
            await router.complete(_REQUEST)

    async def test_all_invalid_responses_map_to_502(self) -> None:
        providers = [
            FakeProvider("a", [AiInvalidResponseError()]),
            FakeProvider("b", [AiInvalidResponseError()]),
        ]
        router = LlmRouter(providers)

        with pytest.raises(AiInvalidResponseError):
            await router.complete(_REQUEST)

    async def test_mixed_down_and_invalid_maps_to_503(self) -> None:
        # One provider answered garbage but another never answered at all:
        # the service could not complete the request - 503 wins.
        providers = [
            FakeProvider("garbage", [AiInvalidResponseError()]),
            FakeProvider("down", [AiUnavailableError()]),
        ]
        router = LlmRouter(providers)

        with pytest.raises(AiUnavailableError):
            await router.complete(_REQUEST)


class TestDataResidency:
    async def test_local_only_request_without_clearance_fails_closed(self) -> None:
        cloud_provider = FakeProvider("cloud", ["should-not-happen"], local_only=False)
        router = LlmRouter([cloud_provider])

        with pytest.raises(AiDataResidencyError):
            await router.complete(_REQUEST, require_local_only=True)
        assert cloud_provider.calls == 0

    async def test_local_only_request_routed_only_to_cleared_providers(self) -> None:
        cloud = FakeProvider("cloud", ["LEAK"], local_only=False)
        local = FakeProvider("local-gateway", ["safe-answer"], local_only=True)
        router = LlmRouter([cloud, local])

        completion = await router.complete(_REQUEST, require_local_only=True)

        assert completion.text == "safe-answer"
        assert cloud.calls == 0  # never even attempted
        assert local.calls == 1

    async def test_cleared_but_exhausted_still_503(self) -> None:
        local = FakeProvider("local-gateway", [AiUnavailableError()], local_only=True)
        router = LlmRouter([local])

        with pytest.raises(AiUnavailableError):
            await router.complete(_REQUEST, require_local_only=True)


class TestFlags:
    def test_has_providers_reflects_configuration(self) -> None:
        assert LlmRouter([]).has_providers is False
        assert LlmRouter([FakeProvider("a", [])]).has_providers is True

    def test_provider_count(self) -> None:
        assert LlmRouter([FakeProvider("a", []), FakeProvider("b", [])]).provider_count == 2
