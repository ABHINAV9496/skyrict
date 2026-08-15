"""CRM scope-filter tests — the SQL predicate produced by ``_scope_filter``.

The filter must fail closed: a missing user/team id narrows the result, never
broadens it. These tests compile the predicate against the PostgreSQL dialect
(the only dialect the service runs on) and assert its structure.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from core.domain.value_objects import DataScope
from core.features.crm.models.lead import ErpCrmLeadModel
from core.features.crm.repository import _scope_filter

_USER_ID = uuid.uuid4()
_TEAM_ID = uuid.uuid4()


def _compile(condition) -> str:
    stmt = select(ErpCrmLeadModel.id).where(condition)
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestScopeFilter:
    def test_owner_scope_filters_by_user(self) -> None:
        condition = _scope_filter(
            scope=DataScope.OWNER,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=_USER_ID,
            team_id=None,
        )
        assert condition is not None
        sql = _compile(condition)
        assert f"erp_crm_leads.owner_id = '{_USER_ID}'" in sql
        assert "team_id" not in sql

    def test_owner_scope_without_user_fails_closed(self) -> None:
        condition = _scope_filter(
            scope=DataScope.OWNER,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=None,
            team_id=None,
        )
        assert condition is not None
        assert "false" in _compile(condition)

    def test_team_scope_matches_owner_or_team(self) -> None:
        condition = _scope_filter(
            scope=DataScope.TEAM,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=_USER_ID,
            team_id=_TEAM_ID,
        )
        assert condition is not None
        sql = _compile(condition)
        assert f"erp_crm_leads.owner_id = '{_USER_ID}'" in sql
        assert f"erp_crm_leads.team_id = '{_TEAM_ID}'" in sql
        assert "OR" in sql

    def test_team_scope_with_team_only(self) -> None:
        condition = _scope_filter(
            scope=DataScope.TEAM,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=None,
            team_id=_TEAM_ID,
        )
        assert condition is not None
        sql = _compile(condition)
        assert f"erp_crm_leads.team_id = '{_TEAM_ID}'" in sql
        assert "owner_id" not in sql

    def test_team_scope_without_ids_fails_closed(self) -> None:
        condition = _scope_filter(
            scope=DataScope.TEAM,
            owner=ErpCrmLeadModel.owner_id,
            team=ErpCrmLeadModel.team_id,
            user_id=None,
            team_id=None,
        )
        assert condition is not None
        assert "false" in _compile(condition)

    def test_all_scope_returns_no_predicate(self) -> None:
        # ALL scope means the tenant filter alone (RLS bounds the tenant);
        # ids are ignored by design.
        assert (
            _scope_filter(
                scope=DataScope.ALL,
                owner=ErpCrmLeadModel.owner_id,
                team=ErpCrmLeadModel.team_id,
                user_id=_USER_ID,
                team_id=_TEAM_ID,
            )
            is None
        )
