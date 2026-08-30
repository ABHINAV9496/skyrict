"""HR Copilot service - request orchestration between router and engine.

Owns the cross-cutting concerns the engine knows nothing about: rate limiting
and audit logging (mirrors ``features/nl_query/service.py``). The engine stays
a ground-and-draft pipeline; this layer decides what happens around it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from ai_agent.core.audit_events import AI_HR_COPILOT_EXCHANGE
from ai_agent.core.rate_limit import limiter

if TYPE_CHECKING:
    import uuid

    from ai_agent.core.audit_service import AuditService
    from ai_agent.features.hr_copilot.engine import HrCopilotEngine, HrCopilotResult

logger = structlog.get_logger("ai_agent.hr_copilot_service")


class HrCopilotService:
    """One tenant's Copilot use case with limits and audit."""

    def __init__(
        self,
        *,
        engine: HrCopilotEngine,
        audit: AuditService,
        rate_limit_per_minute: int,
        tenant_limit_per_minute: int,
    ) -> None:
        self._engine = engine
        self._audit = audit
        self._rate_limit_per_minute = rate_limit_per_minute
        self._tenant_limit_per_minute = tenant_limit_per_minute

    async def ask(
        self,
        *,
        message: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> HrCopilotResult:
        """Enforce limits, run the engine, persist the audit event."""
        await limiter.enforce(
            key=f"ai:hr_copilot:{tenant_id}:{user_id}",
            limit=self._rate_limit_per_minute,
            window_seconds=60,
        )
        await limiter.enforce(
            key=f"ai:tenant_total:{tenant_id}",
            limit=self._tenant_limit_per_minute,
            window_seconds=60,
        )

        result = await self._engine.ask(message)

        summary = result.answer[:200]
        await self._audit.log(
            action=AI_HR_COPILOT_EXCHANGE,
            tenant_id=tenant_id,
            user_id=user_id,
            input_payload={"message_summary": message.strip()[:200]},
            output_payload={"answer_summary": summary, "context_used": result.context_used},
            model_used=result.model_used,
            latency_ms=result.latency_ms,
        )
        logger.info(
            "hr_copilot.completed",
            latency_ms=result.latency_ms,
            model_used=result.model_used,
        )
        return result
