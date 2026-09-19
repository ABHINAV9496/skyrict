"""Unit tests for the deterministic in-process MockProvider and its registry wiring.

These assertions pin the contract the E2E suite depends on: the mock must
produce payloads the REAL engines accept (supervisor classification, report
spec validation, finance journal draft) and must raise the typed AI errors the
router's failover logic keys on.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ai_agent.core.exceptions import AiRateLimitError, AiUnavailableError
from ai_agent.core.providers import LlmRequest, MockProvider
from ai_agent.core.providers.registry import (
    NO_NETWORK_KEYS,
    build_provider,
    build_providers_from_settings,
)
from ai_agent.features.account_suggest.schemas import AccountOption, SuggestRequest
from ai_agent.features.account_suggest.suggest import draft_entry
from ai_agent.features.report_builder.spec import (
    parse_report_spec_payload,
    report_spec_system_prompt,
)
from ai_agent.features.report_builder.validator import validate_spec
from ai_agent.features.supervisor.prompts import CLASSIFY_SYSTEM_PROMPT


def _request(system: str = "", user: str = "") -> LlmRequest:
    return LlmRequest(system_prompt=system, user_prompt=user)


class TestMockProviderResponses:
    async def test_classification_matches_real_prompt_and_routes_inventory(self) -> None:
        provider = MockProvider()
        completion = await provider.complete(
            _request(system=CLASSIFY_SYSTEM_PROMPT, user="Do we have any SKUs below reorder point?")
        )
        payload = json.loads(completion.text)
        assert payload["agents"] == ["inventory_monitor"]
        assert 0.0 <= payload["confidence"] <= 1.0

    async def test_greeting_routes_to_no_agent(self) -> None:
        provider = MockProvider()
        completion = await provider.complete(
            _request(system=CLASSIFY_SYSTEM_PROMPT, user="Hello there")
        )
        payload = json.loads(completion.text)
        assert payload["agents"] == []
        assert payload["confidence"] == 0.0

    async def test_report_spec_matches_real_prompt_and_validates_ready(self) -> None:
        catalog_entry = SimpleNamespace(
            slug="stock_on_hand_vs_reorder",
            title="Stock on hand vs reorder point",
            dataset="products at or below their reorder point",
            dimensions=("sku", "product name"),
            measures=("qty on hand", "reorder point", "gap to reorder"),
        )
        provider = MockProvider()
        completion = await provider.complete(
            _request(
                system=report_spec_system_prompt([catalog_entry]),
                user="Show products below reorder point",
            )
        )
        spec = parse_report_spec_payload(completion.text)
        outcome = await validate_spec(
            spec,
            definitions=[catalog_entry],  # type: ignore[list-item]
            confidence_threshold=0.5,
        )
        assert outcome.resolution.kind == "ready"
        assert outcome.definition is catalog_entry

    async def test_finance_draft_is_balanced_from_inline_chart(self) -> None:
        provider = MockProvider()
        request = SuggestRequest(
            description="E2E test expense for 500",
            accounts=[
                AccountOption(code="1500", name="Equipment"),
                AccountOption(code="1000", name="Cash"),
            ],
        )
        draft = await draft_entry(provider, request)  # type: ignore[arg-type]
        assert draft is not None
        assert [line.side for line in draft.lines] == ["debit", "credit"]
        assert {line.account_code for line in draft.lines} == {"1500", "1000"}
        assert sum(line.amount for line in draft.lines if line.side == "debit") == (
            sum(line.amount for line in draft.lines if line.side == "credit")
        )

    async def test_finance_draft_with_too_small_chart_falls_back_to_prose(self) -> None:
        provider = MockProvider()
        request = SuggestRequest(
            description="Single account", accounts=[AccountOption(code="1000", name="Cash")]
        )
        draft = await draft_entry(provider, request)  # type: ignore[arg-type]
        assert draft is None

    async def test_module_prose_echoes_matching_tool_context(self) -> None:
        provider = MockProvider()
        prompt = (
            "User question: what is the stock level for WIDGET-42?\n\n"
            "Reference context:\n"
            "Live stock: 3 units on hand, 0 reserved across 1 warehouse(s).\n"
            "Product levels:\n"
            "- Blue Widget (WIDGET-42): on hand=3, reorder point=10, unit cost=12.5\n"
        )
        completion = await provider.complete(_request(user=prompt))
        assert "WIDGET-42" in completion.text

    async def test_stream_concatenates_to_complete_text(self) -> None:
        provider = MockProvider()
        request = _request(user="hello world")
        completion = await provider.complete(request)
        chunks = [chunk.token_delta async for chunk in provider.stream(request)]
        assert "".join(chunks) == completion.text


class TestMockProviderFailureModes:
    async def test_degrade_503_raises_before_first_stream_yield(self) -> None:
        provider = MockProvider(behavior="degrade_503")
        with pytest.raises(AiUnavailableError):
            await provider.complete(_request(user="hi"))
        with pytest.raises(AiUnavailableError):
            await anext(provider.stream(_request(user="hi")))

    async def test_rate_limit_429_raises_typed_error(self) -> None:
        provider = MockProvider(behavior="rate_limit_429")
        with pytest.raises(AiRateLimitError):
            await provider.complete(_request(user="hi"))

    async def test_fail_after_lets_first_calls_succeed_then_fails(self) -> None:
        provider = MockProvider(behavior="degrade_503", fail_after=1)
        ok = await provider.complete(_request(user="hi"))
        assert ok.text
        with pytest.raises(AiUnavailableError):
            await provider.complete(_request(user="hi"))

    def test_rejects_unknown_behavior(self) -> None:
        with pytest.raises(ValueError, match="unknown mock behavior"):
            MockProvider(behavior="explode")  # type: ignore[arg-type]


class TestMockRegistryWiring:
    def test_mock_key_builds_without_base_url_or_network(self) -> None:
        assert "mock" in NO_NETWORK_KEYS
        provider = build_provider(provider_key="mock", model="mock-e2e", timeout_seconds=5)
        assert isinstance(provider, MockProvider)
        assert provider.local_only is True
        assert provider.model == "mock-e2e"

    async def test_settings_build_mock_with_scripted_behavior(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AI_PROVIDER", "mock")
        monkeypatch.setenv("AI_MODEL", "mock-e2e")
        monkeypatch.setenv("AI_MOCK_BEHAVIOR", "degrade_503")
        from ai_agent.core.config import Settings

        config = Settings(_env_file=None)  # type: ignore[call-arg]
        providers = build_providers_from_settings(config)

        assert [p.name for p in providers] == ["mock"]
        assert isinstance(providers[0], MockProvider)
        with pytest.raises(AiUnavailableError):
            await providers[0].complete(_request(user="hi"))
