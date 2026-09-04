"""Unit tests for the agent-side RBAC resolution (SKY-59).

Postgres-specific constructs (the composite-tenant join into core_roles) are
asserted by compiling against the PostgreSQL dialect; the flattening/answer
logic runs against a fake session. The compiled JOIN predicate is the security
contract: a grant must only ever pull permissions from a role in the SAME
tenant as the caller.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from ai_agent.db.permission_repository import PermissionRepository
from ai_agent.graphs.security import PERM_INVENTORY_AI_APPROVE, PERM_INVENTORY_READ

TENANT_ID = uuid.uuid4()
USER_ID = uuid.uuid4()


class _FakeResult:
    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self._rows = rows or []

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[list[str]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[list[str]] | None = None) -> None:
        self.rows = rows
        self.executed: list[object] = []

    async def execute(self, statement: object) -> _FakeResult:
        self.executed.append(statement)
        return _FakeResult(self.rows)


def _compile(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "granted_rows,expected",
    [
        # Direct match on a single role.
        ([[PERM_INVENTORY_READ]], [PERM_INVENTORY_READ]),
        # Two roles held by the user - both arrays are flattened.
        (
            [[PERM_INVENTORY_READ], [PERM_INVENTORY_AI_APPROVE]],
            [PERM_INVENTORY_READ, PERM_INVENTORY_AI_APPROVE],
        ),
        # One role array carrying both keys.
        (
            [[PERM_INVENTORY_READ, PERM_INVENTORY_AI_APPROVE]],
            [PERM_INVENTORY_READ, PERM_INVENTORY_AI_APPROVE],
        ),
    ],
)
async def test_flattens_role_arrays_into_permission_list(
    granted_rows: list[list[str]], expected: list[str]
) -> None:
    session = _FakeSession(granted_rows)
    repo = PermissionRepository(session)  # type: ignore[arg-type]

    permissions = await repo.resolve_user_permissions(user_id=USER_ID, tenant_id=TENANT_ID)

    assert permissions == expected


async def test_empty_result_is_empty_permissions() -> None:
    session = _FakeSession([])
    repo = PermissionRepository(session)  # type: ignore[arg-type]

    permissions = await repo.resolve_user_permissions(user_id=USER_ID, tenant_id=TENANT_ID)

    assert permissions == []


async def test_join_is_scoped_by_composite_tenant_key() -> None:
    session = _FakeSession([])
    repo = PermissionRepository(session)  # type: ignore[arg-type]

    await repo.resolve_user_permissions(user_id=USER_ID, tenant_id=TENANT_ID)

    assert len(session.executed) == 1
    sql = _compile(session.executed[0])
    assert "FROM core_roles JOIN core_user_roles" in sql
    # The composite join key is (tenant_id, role_id) - a grant can never pull
    # permissions from a role outside the caller's tenant.
    assert "core_user_roles.tenant_id = core_roles.tenant_id" in sql.replace("\n", " ")
    assert "core_user_roles.role_id = core_roles.id" in sql.replace("\n", " ")


async def test_where_filters_on_caller_identity_and_tenant() -> None:
    session = _FakeSession([])
    repo = PermissionRepository(session)  # type: ignore[arg-type]

    await repo.resolve_user_permissions(user_id=USER_ID, tenant_id=TENANT_ID)

    compiled = session.executed[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined,union-attr]
    sql = str(compiled)
    assert "core_user_roles.user_id" in sql
    assert "core_user_roles.tenant_id" in sql
    # Bound values carry the caller's identity - never an inline literal.
    assert compiled.params["user_id_1"] == USER_ID
    assert compiled.params["tenant_id_1"] == TENANT_ID


class TestHasPermission:
    async def test_exact_grant_passes(self) -> None:
        session = _FakeSession([[PERM_INVENTORY_READ]])
        repo = PermissionRepository(session)  # type: ignore[arg-type]

        assert await repo.has_permission(
            user_id=USER_ID, tenant_id=TENANT_ID, required=PERM_INVENTORY_READ
        )

    async def test_missing_grant_fails_closed(self) -> None:
        session = _FakeSession([[PERM_INVENTORY_READ]])
        repo = PermissionRepository(session)  # type: ignore[arg-type]

        assert not await repo.has_permission(
            user_id=USER_ID, tenant_id=TENANT_ID, required=PERM_INVENTORY_AI_APPROVE
        )
