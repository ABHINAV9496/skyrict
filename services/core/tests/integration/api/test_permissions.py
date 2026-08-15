"""Permission enforcement integration tests (HR-BE-002 §7 error table).

Every HR/Payroll endpoint requires a valid access JWT AND a DB-resolved
permission. ``seeded_test_rbac`` grants the deterministic admin identity the
six ERP keys; the ``unprivileged`` identity has a valid token but zero grants.

Assertions follow the spec's error table:
  401 authentication-error   — missing/invalid token
  403 permission-denied   — valid JWT, missing permission
  200/201                    — valid JWT with the required grant
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.db.session import async_session_factory
from core.models.core_role import CoreRoleModel
from core.models.core_user_role import CoreUserRoleModel

from .helpers import make_tenant_headers

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient

pytestmark = pytest.mark.integration


class TestAuthentication:
    async def test_read_endpoint_requires_token(self, client: AsyncClient) -> None:
        # Tenant context present, no Authorization header → route-level auth.
        response = await client.get("/api/v1/hr/employees", headers={"X-Tenant-Slug": "olympus"})
        assert response.status_code == 401
        assert response.json()["type"].endswith("/authentication-error")

    async def test_write_endpoint_requires_token(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/hr/departments",
            json={"name": "X"},
            headers={"X-Tenant-Slug": "olympus"},
        )
        assert response.status_code == 401
        assert response.json()["type"].endswith("/authentication-error")


class TestHrPermissions:
    async def test_read_denied_without_grant(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.get(
            "/api/v1/hr/employees", headers=tenant_headers(unprivileged=True)
        )
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")

    async def test_read_allowed_with_grant(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.get("/api/v1/hr/employees", headers=tenant_headers())
        assert response.status_code == 200

    async def test_write_denied_for_read_only_identity(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.post(
            "/api/v1/hr/departments",
            json={"name": "Illegal"},
            headers=tenant_headers(unprivileged=True),
        )
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")

    async def test_write_allowed_with_grant(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.post(
            "/api/v1/hr/departments", json={"name": "Legal"}, headers=tenant_headers()
        )
        assert response.status_code == 201

    async def test_approve_denied_without_approve_key(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        # Nobody: zero grants → approve must fail closed before any lookup.
        response = await client.post(
            "/api/v1/hr/leave/requests/00000000-0000-0000-0000-000000000000/approve",
            headers=tenant_headers(unprivileged=True),
        )
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")


class TestPayrollPermissions:
    async def test_read_denied_without_grant(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.get(
            "/api/v1/payroll/settings", headers=tenant_headers(unprivileged=True)
        )
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")

    async def test_read_allowed_with_grant(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.get("/api/v1/payroll/settings", headers=tenant_headers())
        assert response.status_code == 200

    async def test_write_denied_for_read_only_identity(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.post(
            "/api/v1/payroll/runs",
            json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
            headers=tenant_headers(unprivileged=True),
        )
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")

    async def test_write_allowed_with_grant(
        self, client: AsyncClient, tenant_headers: Callable[..., dict[str, str]]
    ) -> None:
        response = await client.post(
            "/api/v1/payroll/runs",
            json={"period_start": "2026-03-01", "period_end": "2026-03-31"},
            headers=tenant_headers(),
        )
        assert response.status_code == 201


# ---------------------------------------------------------------------------
# Scope matrix: system-role grants vs the gated endpoints (docs §2.4 role
# catalog -> route dependencies). Each role is granted to a deterministic sub
# (uuid5 of "skyrict:test:olympus:<role>") and exercised against the five
# ERP-gated routes below.
# ---------------------------------------------------------------------------

_OLYMPUS = "olympus"
_NON_ADMIN_SCOPE_ROLES = ("standard_user", "department_manager", "auditor")


def _role_sub(slug: str, role: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"skyrict:test:{slug}:{role}"))


async def _grant_role(tenant_id: str, role_name: str, sub: str) -> None:
    """Link ``sub`` to the tenant's ``role_name`` (idempotent insert-or-ignore).

    Mirrors the grant in ``api/conftest.py::seeded_test_rbac``; the role rows
    themselves are seeded by that autouse fixture via ``seed_core_roles_for_tenant``.
    """
    async with async_session_factory() as session:
        role_id = await session.scalar(
            select(CoreRoleModel.id).where(
                CoreRoleModel.tenant_id == uuid.UUID(tenant_id),
                CoreRoleModel.name == role_name,
            )
        )
        assert role_id is not None, f"{role_name!r} role must be seeded"
        await session.execute(
            pg_insert(CoreUserRoleModel)
            .values(
                tenant_id=uuid.UUID(tenant_id),
                id=uuid.uuid4(),
                user_id=uuid.UUID(sub),
                role_id=role_id,
                scope_id=None,
            )
            .on_conflict_do_nothing()
        )
        await session.commit()


class TestScopeMatrix:
    """One row per system role asserting every ERP-gated route it may touch.

    Gated routes and their required keys (docs §2.4, routers/hr.py + payroll.py):
      GET  /hr/employees                  erp.hr.read
      POST /hr/employees                  erp.hr.write
      POST /hr/leave/requests/{id}/approve  erp.hr.approve
      GET  /payroll/settings              erp.payroll.read
      POST /payroll/runs                  erp.payroll.write

    Expected outcomes per role:
      standard_user      read only -> 200/403/403/403/403
      department_manager read+write, payroll read -> 200/201/403/200/403
      auditor            hr.read + payroll.read -> 200/403/403/200/403
      organization_admin all six keys -> 200/201/404(passes gate, no request)/200/201
    """

    async def _assert_scope(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        *,
        hr_read: int,
        hr_write: int,
        approve: int,
        payroll_read: int,
        payroll_write: int,
    ) -> None:
        checks = [
            ("GET", "/api/v1/hr/employees", None, hr_read),
            (
                "POST",
                "/api/v1/hr/employees",
                {
                    "first_name": "Scope",
                    "last_name": "Test",
                    "job_title": "Engineer",
                    "hire_date": "2026-01-05",
                    "monthly_salary": "5000.00",
                },
                hr_write,
            ),
            (
                "POST",
                "/api/v1/hr/leave/requests/00000000-0000-0000-0000-000000000000/approve",
                None,
                approve,
            ),
            ("GET", "/api/v1/payroll/settings", None, payroll_read),
            (
                "POST",
                "/api/v1/payroll/runs",
                {"period_start": "2026-03-01", "period_end": "2026-03-31"},
                payroll_write,
            ),
        ]
        for method, path, payload, expected in checks:
            response = await client.request(method, path, json=payload, headers=headers)
            assert response.status_code == expected, (
                f"{method} {path}: expected {expected}, got {response.status_code}: {response.text}"
            )

    async def _role_headers(
        self, rsa_private_key: str, integration_db: dict[str, str], role: str
    ) -> dict[str, str]:
        return make_tenant_headers(
            rsa_private_key,
            integration_db["acme_id"],
            _OLYMPUS,
            sub=_role_sub(_OLYMPUS, role),
        )

    async def _grant_and_headers(
        self,
        rsa_private_key: str,
        integration_db: dict[str, str],
        role: str,
    ) -> dict[str, str]:
        await _grant_role(integration_db["acme_id"], role, _role_sub(_OLYMPUS, role))
        return await self._role_headers(rsa_private_key, integration_db, role)

    async def test_standard_user_scope(
        self,
        client: AsyncClient,
        rsa_private_key: str,
        integration_db: dict[str, str],
    ) -> None:
        headers = await self._grant_and_headers(rsa_private_key, integration_db, "standard_user")
        await self._assert_scope(
            client,
            headers,
            hr_read=200,
            hr_write=403,
            approve=403,
            payroll_read=403,
            payroll_write=403,
        )

    async def test_department_manager_scope(
        self,
        client: AsyncClient,
        rsa_private_key: str,
        integration_db: dict[str, str],
    ) -> None:
        headers = await self._grant_and_headers(
            rsa_private_key, integration_db, "department_manager"
        )
        await self._assert_scope(
            client,
            headers,
            hr_read=200,
            hr_write=201,
            approve=403,
            payroll_read=200,
            payroll_write=403,
        )

    async def test_auditor_scope(
        self,
        client: AsyncClient,
        rsa_private_key: str,
        integration_db: dict[str, str],
    ) -> None:
        headers = await self._grant_and_headers(rsa_private_key, integration_db, "auditor")
        await self._assert_scope(
            client,
            headers,
            hr_read=200,
            hr_write=403,
            approve=403,
            payroll_read=200,
            payroll_write=403,
        )

    async def test_organization_admin_scope(
        self,
        client: AsyncClient,
        rsa_private_key: str,
        integration_db: dict[str, str],
    ) -> None:
        # The org_admin grant already exists via the autouse seeded_test_rbac,
        # which grants the deterministic *admin* sub (":admin") the role.
        admin_sub = str(uuid.uuid5(uuid.NAMESPACE_URL, "skyrict:test:olympus:admin"))
        headers = make_tenant_headers(
            rsa_private_key,
            integration_db["acme_id"],
            _OLYMPUS,
            sub=admin_sub,
        )
        await self._assert_scope(
            client,
            headers,
            hr_read=200,
            hr_write=201,
            approve=404,  # passed the gate; the request itself does not exist
            payroll_read=200,
            payroll_write=201,
        )
