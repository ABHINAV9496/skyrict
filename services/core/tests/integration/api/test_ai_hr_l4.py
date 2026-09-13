"""Integration test for ``GET /api/v1/ai/hr/l4/payroll-base`` (HR-AI-004, SKY-93).

Runs against a real Postgres (skipped w/o DB; requires ``migrated_schema``).
Covers: the owner-only gate (admin without the planning keys returns 403), a
200 with exact money strings from live ``erp_compensation`` rows, and tenant
isolation (globex admin is still 403).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest
from sqlalchemy import text

from core.db.session import async_session_factory

from .helpers import hire_employee

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

_PLANNING_KEYS = ("erp.ai.invoke", "erp.hr.ai.planning")


async def _grant_planning_keys(tenant_id: uuid.UUID) -> None:
    """Append the L4 gate keys to olympus's organization_admin role.

    Inverts the owner-only default for this test only: the seeded test admin
    sub holds organization_admin, and granting the two keys to that role is the
    cheapest stable stand-in for an owner who passes everything via ``*``.
    """
    async with async_session_factory() as session:
        for key in _PLANNING_KEYS:
            await session.execute(
                text(
                    "UPDATE core_roles SET permissions = array_append(permissions, :key) "
                    "WHERE tenant_id = :tenant_id AND name = 'organization_admin' "
                    "AND NOT (:key = ANY(permissions))"
                ),
                {"key": key, "tenant_id": tenant_id},
            )
        await session.commit()


class TestL4PayrollBase:
    async def test_403_without_planning_permission(
        self,
        client: AsyncClient,
        tenant_headers: Callable[..., dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        # admin holds only the six erp.hr.*/erp.payroll.* keys - not the gate.
        response = await client.get(
            "/api/v1/ai/hr/l4/payroll-base", headers=tenant_headers("olympus")
        )
        assert response.status_code == 403, response.text

    async def test_200_with_exact_money_from_seeded_roster(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        tenant_headers: Callable[..., dict[str, str]],
    ) -> None:
        olympus_id = uuid.UUID(integration_db["acme_id"])
        await _grant_planning_keys(olympus_id)
        headers = tenant_headers("olympus")

        await hire_employee(client, headers, first_name="Ada", monthly_salary="5000.00")
        await hire_employee(client, headers, first_name="Grace", monthly_salary="5250.00")

        response = await client.get("/api/v1/ai/hr/l4/payroll-base", headers=headers)
        assert response.status_code == 200, response.text
        body = cast("dict[str, Any]", response.json()["data"])
        assert body["tenant_id"] == str(olympus_id)
        assert body["headcount"] == 2
        assert body["currency"] == "USD"
        assert body["monthly_salary_total"] == "10250.00"
        assert body["monthly_benefit_cost_total"] == "0.00"
        salaries = sorted(emp["monthly_salary"] for emp in body["employees"])
        assert salaries == ["5000.00", "5250.00"]
        assert all(emp["monthly_benefit_cost"] == "0.00" for emp in body["employees"])

    async def test_tenant_isolation_still_403(
        self,
        client: AsyncClient,
        integration_db: dict[str, str],
        tenant_headers: Callable[..., dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        # Grant only olympus; globex's admin must stay locked out.
        await _grant_planning_keys(uuid.UUID(integration_db["acme_id"]))
        response = await client.get(
            "/api/v1/ai/hr/l4/payroll-base", headers=tenant_headers("globex")
        )
        assert response.status_code == 403, response.text
