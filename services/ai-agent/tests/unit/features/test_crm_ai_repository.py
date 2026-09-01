"""Unit tests for the CRM AI repository (SKY-61 storage layer).

Uses a fake session that records executed statements so the tenant scoping and
status-lifecycle SQL can be asserted against the PostgreSQL dialect without a
live database, and real model objects to exercise the follow-up state
transitions (pending -> sent/dismissed/expired).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects import postgresql

from ai_agent.features.crm.repositories import CrmAiRepository
from ai_agent.models.ai_deal_health import AiDealHealthModel
from ai_agent.models.ai_follow_up_suggestion import AiFollowUpSuggestionModel
from ai_agent.models.ai_lead_score import AiLeadScoreModel

TENANT_ID = uuid.uuid4()
OTHER_TENANT_ID = uuid.uuid4()


class _Result:
    rowcount: int = 0

    def __init__(self, rows: list[object] | None = None) -> None:
        self._rows = rows or []

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _Scalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _FakeSession:
    def __init__(self, result: _Result | None = None) -> None:
        self.executed: list[object] = []
        self._result = result or _Result()
        self.added: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.executed.append(statement)
        return self._result

    async def flush(self) -> None:
        pass

    def add(self, row: object) -> None:
        self.added.append(row)


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


class TestLeadScore:
    async def test_latest_lead_score_is_tenant_scoped_and_ordered_desc(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        await repo.latest_lead_score(tenant_id=TENANT_ID, lead_id=uuid.uuid4())

        sql = _compile(session.executed[0])
        assert "ai_lead_scores" in sql
        assert "tenant_id" in sql
        assert "lead_id" in sql
        assert "ORDER BY ai_lead_scores.computed_at DESC" in sql
        assert "LIMIT" in sql

    async def test_save_lead_score_adds_row(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        row = AiLeadScoreModel(
            tenant_id=TENANT_ID, lead_id=uuid.uuid4(), score=88, factors=["engagement 0.9"]
        )
        await repo.save_lead_score(row)
        assert session.added == [row]


class TestDealHealth:
    async def test_latest_deal_health_is_tenant_and_opportunity_scoped(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        await repo.latest_deal_health(tenant_id=TENANT_ID, opportunity_id=uuid.uuid4())

        sql = _compile(session.executed[0])
        assert "ai_deal_health" in sql
        assert "tenant_id" in sql
        assert "opportunity_id" in sql
        assert "ORDER BY ai_deal_health.computed_at DESC" in sql

    async def test_save_deal_health_adds_row(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        row = AiDealHealthModel(
            tenant_id=TENANT_ID,
            opportunity_id=uuid.uuid4(),
            health="green",
            risk_factors=[],
            recommended_actions=[],
        )
        await repo.save_deal_health(row)
        assert session.added == [row]


class TestFollowUp:
    async def test_list_pending_for_user_filters_status_and_tenant(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        await repo.list_pending_for_user(tenant_id=TENANT_ID, user_id=uuid.uuid4())

        sql = _compile(session.executed[0])
        assert "ai_follow_up_suggestions" in sql
        assert "tenant_id" in sql
        assert "user_id" in sql
        assert "status = %(status" in sql
        assert "ORDER BY ai_follow_up_suggestions.created_at DESC" in sql

    async def test_get_for_apply_is_tenant_scoped(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        await repo.get_for_apply(tenant_id=TENANT_ID, suggestion_id=uuid.uuid4())

        sql = _compile(session.executed[0])
        assert "tenant_id" in sql
        assert "id" in sql

    async def test_mark_applied_mutates_row_and_marks_sent(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        row = _follow_up(status="pending")
        activity_id = uuid.uuid4()
        actor = uuid.uuid4()

        await repo.mark_applied(row=row, applied_by=actor, activity_id=activity_id)

        assert row.status == "sent"
        assert row.sent_at is not None
        assert row.applied_by == actor
        assert row.activity_id == activity_id
        assert session.executed == []  # mutation only, no extra SQL

    async def test_expire_stale_updates_only_pending_and_expired(self) -> None:
        session = _FakeSession(result=_Result())
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        await repo.expire_stale(tenant_id=TENANT_ID)

        sql = _compile(session.executed[0])
        assert "UPDATE ai_follow_up_suggestions" in sql
        assert "status=%(status)s" in sql
        assert "status = %(status_1)s" in sql  # WHERE clause on pending
        assert "expires_at <" in sql
        assert "tenant_id" in sql

    async def test_delete_follow_ups_for_entity_is_scoped(self) -> None:
        session = _FakeSession()
        repo = CrmAiRepository(session)  # type: ignore[arg-type]
        entity_id = uuid.uuid4()
        await repo.delete_follow_ups_for_entity(
            tenant_id=TENANT_ID, entity_type="opportunity", entity_id=entity_id
        )

        sql = _compile(session.executed[0])
        assert "DELETE FROM ai_follow_up_suggestions" in sql
        assert "tenant_id" in sql
        assert "entity_type" in sql
        assert "entity_id" in sql


def _follow_up(*, status: str = "pending") -> AiFollowUpSuggestionModel:
    return AiFollowUpSuggestionModel(
        tenant_id=TENANT_ID,
        user_id=uuid.uuid4(),
        entity_type="lead",
        entity_id=uuid.uuid4(),
        suggestion_type="task",
        draft_content="Follow up on the quote.",
        reasoning="No activity in 5 days.",
        status=status,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
