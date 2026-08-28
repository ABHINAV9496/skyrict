"""HR Copilot engine - assemble aggregate context and draft the answer.

Flow (spec §9, feature 5):
  1. CONTEXT - fetch the tenant's L1 aggregate overview/tenure and leave
     policy through the gateway (aggregate-only; failures degrade to None).
  2. GROUND - build a guardrailed system prompt embedding ONLY that aggregate
     context and the leave policy. No individual/PII data is ever placed in
     the prompt: the Copilot's tool surface performs no individual read, so
     there is nothing per-person to leak even in a refusal.
  3. DRAFT - call the LLM once through ``LlmRouter`` (which runs the PII
     redaction gate over the user message before any provider sees it).
     A refusal to an out-of-scope request is a normal answer, not an error.

Data residency: aggregate counts, band labels, and policy figures may travel
to cloud providers (``require_local_only=False``) - identical to the inventory
NL parser. The redaction gate is the backstop for any stray PII.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from ai_agent.core.providers import LlmRequest

if TYPE_CHECKING:
    from ai_agent.core.llm_router import LlmRouter
    from ai_agent.features.hr_copilot.gateway import (
        HrGatewayPort,
        HrLeavePolicyCtx,
        HrOverviewCtx,
        HrTenureCtx,
    )

logger = structlog.get_logger("ai_agent.hr_copilot_engine")

_COPILOT_SYSTEM_PROMPT = (
    "You are the SkyRICT HR Copilot, a helpful assistant for HR managers and "
    "department heads. Answer the user's question about their organisation "
    "using ONLY the CONTEXT provided below, which contains AGGREGATE headcount, "
    "tenure-band, and leave-policy information. No other data is available to you.\n"
    "\n"
    "Hard rules:\n"
    "1. You must NEVER reveal, guess, or discuss any individual employee's "
    "personal or financial data (names, salaries, individual records, or "
    "anything identifying one person). If asked about a specific person or "
    "any individual's data, politely refuse and explain that you can only "
    "answer from aggregate and policy information.\n"
    "2. Answer only what the CONTEXT supports. Do not invent figures. If a "
    "figure is not in the CONTEXT, say it is not available to you.\n"
    "3. Keep answers concise and factual.\n"
)


@dataclass(frozen=True, slots=True)
class HrCopilotResult:
    """Everything the Copilot chat returns plus what the audit log needs."""

    answer: str
    model_used: str | None
    latency_ms: int
    context_used: dict[str, object] | None


class HrCopilotEngine:
    """Ground one Copilot message in aggregate HR context and draft an answer."""

    def __init__(
        self,
        *,
        llm_router: LlmRouter,
        gateway_factory: HrGatewayPort | None,
    ) -> None:
        self._llm_router = llm_router
        # A callable gateway (bound per request). Fake-friendly: may be None
        # for tests that exercise only the LLM path.
        self._gateway = gateway_factory

    async def ask(self, message: str) -> HrCopilotResult:
        started = time.perf_counter()

        overview = await self._gateway.get_overview() if self._gateway is not None else None
        tenure = await self._gateway.get_tenure() if self._gateway is not None else None
        policy = await self._gateway.get_leave_policy() if self._gateway is not None else None

        context = _build_context(overview=overview, tenure=tenure, policy=policy)

        completion = await self._llm_router.complete(
            LlmRequest(
                system_prompt=_COPILOT_SYSTEM_PROMPT + "\n\nCONTEXT:\n" + context,
                user_prompt=message.strip(),
                max_tokens=512,
                temperature=0.2,
            )
        )

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "hr_copilot.completed",
            latency_ms=latency_ms,
            model_used=completion.model_used,
        )
        return HrCopilotResult(
            answer=completion.text,
            model_used=completion.model_used,
            latency_ms=latency_ms,
            context_used=_context_summary(overview=overview, tenure=tenure, policy=policy),
        )


def _build_context(
    *,
    overview: HrOverviewCtx | None,
    tenure: HrTenureCtx | None,
    policy: HrLeavePolicyCtx | None,
) -> str:
    """Render the aggregate context into a readable prompt block."""
    lines: list[str] = []
    if overview is not None:
        headcount = overview.total_headcount or 0
        lines.append(f"- Current headcount: {headcount}")
        if overview.departments:
            depts = ", ".join(f"{name} ({count})" for name, count in overview.departments)
            lines.append(f"- Headcount by department: {depts}.")
        if overview.tenure_bands:
            bands = ", ".join(f"{band} ({count})" for band, count in overview.tenure_bands)
            lines.append(f"- Tenure bands: {bands}.")
        if overview.narrative:
            lines.append(f"- Overview narrative: {overview.narrative}")
    if tenure is not None and tenure.narrative:
        lines.append(f"- Tenure narrative: {tenure.narrative}")
    if policy is not None:
        policy_parts: list[str] = []
        if policy.casual_days_per_year is not None:
            policy_parts.append(f"casual leave {policy.casual_days_per_year} days/year")
        if policy.sick_days_per_year is not None:
            policy_parts.append(f"sick leave {policy.sick_days_per_year} days/year")
        if policy.effective_from:
            policy_parts.append(f"effective from {policy.effective_from}")
        if policy_parts:
            lines.append("- Leave policy: " + "; ".join(policy_parts) + ".")
    if not lines:
        lines.append(
            "No aggregate HR context is currently available for this tenant. "
            "Answer only that context is unavailable; do not guess figures."
        )
    return "\n".join(lines)


def _context_summary(
    *,
    overview: HrOverviewCtx | None,
    tenure: HrTenureCtx | None,
    policy: HrLeavePolicyCtx | None,
) -> dict[str, object] | None:
    """Which context parts were available - for the audit log / response."""
    summary: dict[str, object] = {}
    if overview is not None:
        summary["overview"] = True
    if tenure is not None:
        summary["tenure"] = True
    if policy is not None:
        summary["leave_policy"] = True
    return summary or None
