"""AuditService unit tests - port double, no database."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from ai_agent.core.audit_events import AI_QUERY_EXECUTED, AI_SUGGESTION_APPROVED
from ai_agent.core.audit_service import AuditService


class FakeAiAuditRepository:
    """Records add() calls; satisfies AiAuditRepositoryPort structurally."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []

    async def add(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        user_id: uuid.UUID | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        model_used: str | None = None,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "action": action,
            "user_id": user_id,
            "input_payload": input_payload,
            "output_payload": output_payload,
            "model_used": model_used,
            "latency_ms": latency_ms,
        }
        self.added.append(row)
        return row


class TestAuditService:
    async def test_log_delegates_known_action(self) -> None:
        repo = FakeAiAuditRepository()
        service = AuditService(repo)
        tenant = uuid.uuid4()
        user = uuid.uuid4()

        row = await service.log(
            action=AI_QUERY_EXECUTED,
            tenant_id=tenant,
            user_id=user,
            input_payload={"query_text_len": 24},
            output_payload={"rows_returned": 3},
            model_used="openrouter/test-model",
            latency_ms=812,
        )

        assert repo.added == [row]
        assert row["tenant_id"] == tenant
        assert row["user_id"] == user
        assert row["action"] == AI_QUERY_EXECUTED
        assert row["model_used"] == "openrouter/test-model"
        assert row["latency_ms"] == 812

    async def test_system_job_has_no_user(self) -> None:
        # Background scans audit with user_id=None (spec §5.3).
        repo = FakeAiAuditRepository()
        service = AuditService(repo)

        await service.log(
            action=AI_SUGGESTION_APPROVED,
            tenant_id=uuid.uuid4(),
        )

        assert repo.added[0]["user_id"] is None

    async def test_unknown_action_rejected(self) -> None:
        repo = FakeAiAuditRepository()
        service = AuditService(repo)

        with pytest.raises(ValueError, match="unknown audit action"):
            await service.log(action="ai.hallucinated.event", tenant_id=uuid.uuid4())

        assert repo.added == []
