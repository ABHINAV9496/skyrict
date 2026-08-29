"""Unit tests for the HR Copilot engine.

Exercised with a scripted LLM router double and an in-memory gateway double -
no network or database. Focus: the aggregate context is grounded into the
prompt, the individual/PII refusal guardrail is always present, and a missing
context part degrades to an explicit "unavailable" instruction rather than a
fabricated figure.
"""

from __future__ import annotations

from ai_agent.core.providers.base import LlmCompletion, LlmRequest
from ai_agent.features.hr_copilot.engine import HrCopilotEngine
from ai_agent.features.hr_copilot.gateway import (
    HrLeavePolicyCtx,
    HrOverviewCtx,
    HrTenureCtx,
)


class FakeLlmRouter:
    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[LlmRequest] = []

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        self.requests.append(request)
        return LlmCompletion(text=self.text, model_used="fake-model", latency_ms=1)


class FakeGateway:
    def __init__(
        self,
        *,
        overview: HrOverviewCtx | None,
        tenure: HrTenureCtx | None,
        policy: HrLeavePolicyCtx | None,
    ) -> None:
        self.overview = overview
        self.tenure = tenure
        self.policy = policy
        self.calls: list[str] = []

    async def get_overview(self) -> HrOverviewCtx | None:
        self.calls.append("overview")
        return self.overview

    async def get_tenure(self) -> HrTenureCtx | None:
        self.calls.append("tenure")
        return self.tenure

    async def get_leave_policy(self) -> HrLeavePolicyCtx | None:
        self.calls.append("policy")
        return self.policy


def _overview() -> HrOverviewCtx:
    return HrOverviewCtx(
        total_headcount=120,
        departments=(("Engineering", 40), ("Sales", 25)),
        tenure_bands=(("1-3", 70), ("3-5", 30)),
        narrative="Headcount grew 4% MoM.",
    )


def _policy() -> HrLeavePolicyCtx:
    return HrLeavePolicyCtx(
        casual_days_per_year=12,
        sick_days_per_year=8,
        effective_from="2026-01-01",
    )


_MISSING = object()  # distinguishes "not provided" from an explicit None context


def _make_engine(
    llm_text: str,
    *,
    overview: object = _MISSING,
    tenure: HrTenureCtx | None = None,
    policy: object = _MISSING,
) -> tuple[HrCopilotEngine, FakeLlmRouter, FakeGateway]:
    router = FakeLlmRouter(llm_text)
    gateway = FakeGateway(
        overview=_overview() if overview is _MISSING else overview,
        tenure=tenure,
        policy=_policy() if policy is _MISSING else policy,
    )
    engine = HrCopilotEngine(
        llm_router=router,  # type: ignore[arg-type]
        gateway_factory=gateway,  # type: ignore[arg-type]
    )
    return engine, router, gateway


class TestGrounding:
    async def test_aggregate_context_grounded_into_prompt(self) -> None:
        engine, router, gateway = _make_engine("Here is the answer.")
        tenure = HrTenureCtx(narrative="Tenure concentrated at 1-3 years.")
        gateway.tenure = tenure

        result = await engine.ask("How big is our headcount?")

        assert result.answer == "Here is the answer."
        assert result.model_used == "fake-model"
        system = router.requests[0].system_prompt
        assert "Current headcount: 120" in system
        assert "Engineering (40)" in system
        assert "1-3 (70)" in system
        assert "casual leave 12 days/year" in system
        assert "Tenure narrative: Tenure concentrated at 1-3 years." in system
        # The user message carries only the question (no PII prompt data).
        assert router.requests[0].user_prompt == "How big is our headcount?"
        assert gateway.calls == ["overview", "tenure", "policy"]
        assert result.context_used == {"overview": True, "tenure": True, "leave_policy": True}

    async def test_pii_refusal_guardrail_always_in_system_prompt(self) -> None:
        engine, router, _ = _make_engine("Ignore me")

        await engine.ask("What is Kumar's salary?")

        system = router.requests[0].system_prompt
        assert "NEVER" in system
        assert "individual employee" in system
        assert "salaries" in system

    async def test_missing_context_instructs_not_to_invent(self) -> None:
        engine, router, _ = _make_engine("ok", overview=None, tenure=None, policy=None)

        result = await engine.ask("what is our headcount?")

        system = router.requests[0].system_prompt
        assert "unavailable" in system
        assert "do not guess" in system
        # No aggregate context was sourced - nothing to leak to the prompt.
        assert result.context_used is None
