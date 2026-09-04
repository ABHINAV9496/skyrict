"""Data-scope resolution tests - role -> DataScope mapping (core/db/rbac.py).

The mapping is the ONE place role names become row-scoping rules; feature
repositories only ever receive a resolved :class:`DataScope`. Unknown roles
must fail closed to OWNER - a user can never see MORE than their role grants.
"""

from __future__ import annotations

from core.db.rbac import resolve_data_scope
from core.domain.value_objects import DataScope


class TestResolveDataScope:
    def test_owner_roles_see_everything(self) -> None:
        assert resolve_data_scope("owner") is DataScope.ALL
        assert resolve_data_scope("tenant_owner") is DataScope.ALL
        assert resolve_data_scope("organization_admin") is DataScope.ALL

    def test_auditor_reads_everything(self) -> None:
        assert resolve_data_scope("auditor") is DataScope.ALL

    def test_manager_sees_team(self) -> None:
        assert resolve_data_scope("department_manager") is DataScope.TEAM

    def test_standard_user_sees_own_rows(self) -> None:
        assert resolve_data_scope("standard_user") is DataScope.OWNER

    def test_unknown_role_fails_closed(self) -> None:
        assert resolve_data_scope("custom_role") is DataScope.OWNER
        assert resolve_data_scope("") is DataScope.OWNER
