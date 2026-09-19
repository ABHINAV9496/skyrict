"""Deterministic, in-process LLM provider for offline tests and E2E runs.

``MockProvider`` lets the E2E suite drive every AI journey through the REAL
supervisor / router / engine code paths with no network call, API key, or
non-determinism. It is selected with ``AI_PROVIDER=mock`` and its failure mode
is scripted with ``AI_MOCK_BEHAVIOR`` (``ok`` | ``degrade_503`` |
``rate_limit_429``) and ``AI_MOCK_FAIL_AFTER``.

It is test infrastructure, NOT a product feature: answers are canned strings
derived from the request, never real model output. Response selection keys off
the system/user prompt shape a caller already sends, so one provider satisfies
all four LLM touch points:

- supervisor classification -> ``{"agents": [...], "confidence": n}``
- report builder            -> a whitelisted :class:`ParsedReportSpec` payload
- finance journal draft     -> a balanced two-line entry from the inline chart
- module answers            -> a short prose answer echoing real tool context
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Literal

from ai_agent.core.exceptions import AiRateLimitError, AiUnavailableError
from ai_agent.core.providers.base import LlmCompletion, LlmStreamChunk

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ai_agent.core.providers.base import LlmRequest

MockBehavior = Literal["ok", "degrade_503", "rate_limit_429"]

_BEHAVIORS: frozenset[str] = frozenset({"ok", "degrade_503", "rate_limit_429"})

# Prompt-shape signatures emitted by the calling engines. Kept as literals so
# this core module never imports a feature module.
_CLASSIFY_SIGNATURE = "route user requests to the right"
_REPORT_SIGNATURE = "CATALOG (the only valid templates)"
_REFERENCE_MARKER = "Reference context:"

_GREETINGS = frozenset({"hi", "hello", "hey", "thanks", "thank you", "how are you"})

# Mirrors supervisor._KEYWORD_RULES so classification matches the deterministic
# fallback ordering without a core -> feature import.
_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "inventory_monitor",
        (
            "stock",
            "inventory",
            "reorder",
            "movement",
            "sku",
            "warehouse",
            "receipt",
            "reserved",
            "on hand",
            "forecast",
            "demand",
        ),
    ),
    (
        "hr_copilot",
        (
            "hr",
            "leave",
            "policy",
            "employee",
            "onboarding",
            "payroll",
            "benefit",
            "appraisal",
            "attrition",
            "headcount",
        ),
    ),
    ("crm_assistant", ("crm", "customer", "lead", "opportunity", "pipeline", "sales")),
    ("finance_assistant", ("finance", "invoice", "revenue", "expense", "budget", "p&l")),
    ("sales_coach", ("coach", "coaching", "follow up", "follow-up", "deal strategy")),
    ("audit_guardian", ("audit", "guardian", "flagged", "suspicious", "integrity")),
)

# A spec that validates against the seeded stock_on_hand_vs_reorder template:
# the dataset matches, sku is a declared dimension, and qty on hand a declared
# measure. Dimensions AND measures must be non-empty (validator requirement).
_REPORT_SPEC: dict[str, object] = {
    "template_slug": "stock_on_hand_vs_reorder",
    "dataset": "products at or below their reorder point",
    "dimensions": ["sku"],
    "measures": ["qty on hand"],
    "filters": ["products below reorder point"],
    "timeframe": None,
    "confidence": 0.95,
}


class MockProvider:
    """Dependency-free :class:`LlmProvider` implementation for tests/E2E."""

    def __init__(
        self,
        *,
        name: str = "mock",
        model: str = "mock-e2e",
        behavior: MockBehavior = "ok",
        fail_after: int = 0,
    ) -> None:
        if behavior not in _BEHAVIORS:
            raise ValueError(f"unknown mock behavior: {behavior!r}")
        if fail_after < 0:
            raise ValueError("fail_after must be >= 0")
        self.name = name
        self.model = model.strip() or "mock-e2e"
        # In-process: never leaves the trust boundary, so it is cleared for
        # local-only data classes (cost/sell prices) by construction.
        self.local_only = True
        self._behavior: MockBehavior = behavior
        self._fail_after = fail_after
        self._productions = 0

    async def complete(self, request: LlmRequest) -> LlmCompletion:
        """Return one scripted completion without touching the network."""
        self._maybe_fail()
        started = time.perf_counter()
        text = self._respond(request)
        latency_ms = max(int((time.perf_counter() - started) * 1000), 1)
        return LlmCompletion(text=text, model_used=self.model, latency_ms=latency_ms)

    async def stream(self, request: LlmRequest) -> AsyncIterator[LlmStreamChunk]:
        """Yield the scripted completion as word deltas.

        The scripted failure is raised BEFORE the first ``yield`` so the router
        may fail over, matching the provider stream contract.
        """
        self._maybe_fail()
        for delta in _chunk_text(self._respond(request)):
            await asyncio.sleep(0)
            yield LlmStreamChunk(token_delta=delta, model_used=self.model)

    # ------------------------------------------------------------------ #
    # Scripted failure
    # ------------------------------------------------------------------ #

    def _maybe_fail(self) -> None:
        if self._behavior == "ok":
            return
        self._productions += 1
        if self._fail_after and self._productions <= self._fail_after:
            return
        if self._behavior == "rate_limit_429":
            raise AiRateLimitError()
        raise AiUnavailableError()

    # ------------------------------------------------------------------ #
    # Response selection
    # ------------------------------------------------------------------ #

    def _respond(self, request: LlmRequest) -> str:
        system = request.system_prompt or ""
        user = request.user_prompt or ""
        if _CLASSIFY_SIGNATURE in system:
            return self._classify(user)
        if _REPORT_SIGNATURE in system:
            return json.dumps(_REPORT_SPEC, ensure_ascii=False)
        if user.startswith("Description:") and "Chart of accounts:" in user:
            return self._finance_draft(user)
        return self._prose(user)

    def _classify(self, user: str) -> str:
        lowered = user.strip().lower()
        if not lowered or lowered in _GREETINGS:
            agents: list[str] = []
        else:
            agents = [
                key for key, keywords in _KEYWORD_RULES if any(w in lowered for w in keywords)
            ]
        confidence = 0.96 if agents else 0.0
        return json.dumps({"agents": agents, "confidence": confidence})

    def _finance_draft(self, user: str) -> str:
        chart_text = user.split("Chart of accounts:", 1)[1].strip()
        try:
            accounts = json.loads(chart_text)
        except json.JSONDecodeError:
            return self._prose(user)
        if not isinstance(accounts, list) or len(accounts) < 2:
            return self._prose(user)
        first, second = accounts[0], accounts[1]
        if not isinstance(first, dict) or not isinstance(second, dict):
            return self._prose(user)
        first_code = str(first.get("code") or "").strip()
        second_code = str(second.get("code") or "").strip()
        if not first_code or not second_code:
            return self._prose(user)
        payload = {
            "lines": [
                {
                    "account_code": first_code,
                    "account_name": str(first.get("name") or ""),
                    "amount": 500,
                    "side": "debit",
                    "description": "E2E mock debit",
                },
                {
                    "account_code": second_code,
                    "account_name": str(second.get("name") or ""),
                    "amount": 500,
                    "side": "credit",
                    "description": "E2E mock credit",
                },
            ],
            "explanation": "Debit the first chart account and credit the second.",
            "confidence": 0.9,
            "reasoning": "Deterministic E2E mock entry.",
        }
        return json.dumps(payload, ensure_ascii=False)

    def _prose(self, user: str) -> str:
        question = ""
        detail = ""
        if _REFERENCE_MARKER in user:
            head, _, tail = user.partition(_REFERENCE_MARKER)
            match = re.search(r"User question:\s*(.*)", head, re.DOTALL)
            question = match.group(1).strip() if match else ""
            detail = _matching_context_line(question, tail.strip())
        else:
            question = user.strip()

        parts = ["Here is a summary based on the live data available to me."]
        if question:
            parts.append(f'You asked: "{_truncate(question, 160)}".')
        if detail:
            parts.append(detail)
        return " ".join(parts)


def _matching_context_line(question: str, context: str) -> str:
    """Pick the context line most relevant to the question.

    The delegate appends real tool output after ``Reference context:``; echoing
    the matching line back proves the tool data reached the model end-to-end
    (product lines carry the SKU the E2E created).
    """
    lines = [
        line.strip()
        for line in context.splitlines()
        if line.strip() and line.strip() != "Product levels:"
    ]
    product_lines = [line for line in lines if line.startswith("- ")]
    words = [word for word in (w.strip("?.,!\"'():") for w in question.split()) if len(word) >= 3]
    for line in product_lines:
        lowered = line.lower()
        if any(word.lower() in lowered for word in words):
            return line
    if product_lines:
        return product_lines[0]
    return lines[0] if lines else ""


def _chunk_text(text: str) -> list[str]:
    """Split text into word deltas that concatenate back to the original."""
    words = text.split(" ")
    return [word + (" " if index < len(words) - 1 else "") for index, word in enumerate(words)]


def _truncate(value: str, limit: int) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
