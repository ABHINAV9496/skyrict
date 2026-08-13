"""seed_core_roles_for_tenant unit tests — fake session factory, no database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING

from core.seed import CORE_SYSTEM_ROLES, seed_core_roles_for_tenant

if TYPE_CHECKING:
    import pytest

    from core.models.core_role import CoreRoleModel


class FakeSession:
    """Record adds/commits and serve canned ``execute`` results."""

    class _Result:
        def __init__(self, rows: list) -> None:
            self._rows = rows

        def scalars(self) -> list:
            return self._rows

    def __init__(self, existing: list[CoreRoleModel] | None = None) -> None:
        self.existing = list(existing or [])
        self.added: list[CoreRoleModel] = []
        self.committed = False

    async def execute(self, stmt: object) -> _Result:
        return self._Result(self.existing)

    def add(self, model: CoreRoleModel) -> None:
        self.added.append(model)

    async def commit(self) -> None:
        self.committed = True


class FakeFactory:
    """Mimics ``async_sessionmaker()`` used as ``async with``."""

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *exc: object) -> None:
        return None


def _existing_role(name: str, permissions: list[str]) -> SimpleNamespace:
    return SimpleNamespace(name=name, permissions=permissions, is_system_role=True)


def _patch_factory(monkeypatch: pytest.MonkeyPatch, session: FakeSession) -> None:
    from core import seed as seed_module

    monkeypatch.setattr(seed_module, "async_session_factory", lambda: FakeFactory(session))


class TestSeedCoreRolesForTenant:
    async def test_creates_all_system_roles_for_fresh_tenant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        session = FakeSession()
        _patch_factory(monkeypatch, session)
        tenant = uuid.uuid4()

        await seed_core_roles_for_tenant(tenant)

        assert session.committed
        assert len(session.added) == len(CORE_SYSTEM_ROLES)
        by_name = {role.name: role for role in session.added}
        assert set(by_name) == {name for name, _ in CORE_SYSTEM_ROLES}
        for name, permissions in CORE_SYSTEM_ROLES:
            role = by_name[name]
            assert role.tenant_id == tenant
            assert role.is_system_role is True
            assert role.permissions == list(permissions)

    async def test_idempotent_when_all_system_roles_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = [
            _existing_role(name, list(permissions)) for name, permissions in CORE_SYSTEM_ROLES
        ]
        session = FakeSession(existing)
        _patch_factory(monkeypatch, session)

        await seed_core_roles_for_tenant(uuid.uuid4())

        assert session.committed
        assert session.added == []
        for role in existing:
            assert role.is_system_role is True

    async def test_merges_missing_keys_and_preserves_custom_grants(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = [_existing_role("organization_admin", ["erp.hr.read", "custom:key"])]
        session = FakeSession(existing)
        _patch_factory(monkeypatch, session)

        await seed_core_roles_for_tenant(uuid.uuid4())

        merged = existing[0]
        assert merged.permissions == [
            "erp.hr.read",
            "custom:key",
            "erp.hr.write",
            "erp.hr.approve",
            "erp.payroll.read",
            "erp.payroll.write",
            "erp.payroll.approve",
        ]
        assert merged.is_system_role is True
        assert len(session.added) == len(CORE_SYSTEM_ROLES) - 1

    async def test_forces_system_role_flag_on_custom_role(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        existing = [SimpleNamespace(name="auditor", permissions=[], is_system_role=False)]
        session = FakeSession(existing)
        _patch_factory(monkeypatch, session)

        await seed_core_roles_for_tenant(uuid.uuid4())

        assert existing[0].is_system_role is True
        assert existing[0].permissions == ["erp.hr.read", "erp.payroll.read"]


class TestCoreSystemRolesDefinition:
    def test_grants_match_design_doc_section_2_4(self) -> None:
        by_name = dict(CORE_SYSTEM_ROLES)

        assert by_name["tenant_owner"] == ("*",)
        assert set(by_name["organization_admin"]) == {
            "erp.hr.read",
            "erp.hr.write",
            "erp.hr.approve",
            "erp.payroll.read",
            "erp.payroll.write",
            "erp.payroll.approve",
        }
        assert by_name["department_manager"] == ("erp.hr.read", "erp.hr.write", "erp.payroll.read")
        assert by_name["standard_user"] == ("erp.hr.read",)
        assert by_name["auditor"] == ("erp.hr.read", "erp.payroll.read")
