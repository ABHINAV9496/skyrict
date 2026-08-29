"""Unit tests for the HR Copilot service orchestration layer."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from ai_agent.core import rate_limit
from ai_agent.core.audit_events import AI_HR_COPILOT_EXCHANGE
from ai_agent.features.hr_copilot.engine import HrCopilotResult
from ai_agent.features.hr_copilot.service import HrCopilotService

if TYPE_CHECKING:
    import pytest

TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER = uuid.UUID("20000000-0000-0000-0000-000000000001")


class FakeEngine:
    async def ask(self, message: str) -> HrCopilotResult:
        return HrCopilotResult(
            answer=f"answer to {message}",
            model_used="fake-model",
            latency_ms=7,
            context_used={"overview": True},
        )


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> Any:
        self.events.append(kwargs)


async def _noop_enforce(**kwargs: Any) -> None:
    return None


def _make_service() -> tuple[HrCopilotService, FakeAudit]:
    audit = FakeAudit()
    service = HrCopilotService(
        engine=FakeEngine(),  # type: ignore[arg-type]
        audit=audit,  # type: ignore[arg-type]
        rate_limit_per_minute=20,
        tenant_limit_per_minute=100,
    )
    return service, audit


class TestService:
    async def test_audits_exchange_and_returns_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(rate_limit.limiter, "enforce", _noop_enforce)
        service, audit = _make_service()

        result = await service.ask(
            message="How many people in Engineering?",
            tenant_id=TENANT,
            user_id=USER,
        )

        assert result.answer == "answer to How many people in Engineering?"
        assert result.model_used == "fake-model"
        # Audit payloads are summaries - never the raw message/prompt/answer.
        (event,) = audit.events
        assert event["action"] == AI_HR_COPILOT_EXCHANGE
        assert event["tenant_id"] == TENANT
        assert event["user_id"] == USER
        assert "message_summary" in event["input_payload"]
        assert "answer_summary" in event["output_payload"]
        assert event["output_payload"]["context_used"] == {"overview": True}
        assert event["model_used"] == "fake-model"
        assert event["latency_ms"] == 7

    async def test_rate_limits_applied_before_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        keys: list[str] = []

        async def recording_enforce(*, key: str, limit: int, window_seconds: int) -> None:
            keys.append(key)

        monkeypatch.setattr(rate_limit.limiter, "enforce", recording_enforce)
        service, _ = _make_service()

        await service.ask(message="hello", tenant_id=TENANT, user_id=USER)

        assert keys == [
            f"ai:hr_copilot:{TENANT}:{USER}",
            f"ai:tenant_total:{TENANT}",
        ]
