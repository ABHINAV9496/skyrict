"""End-to-end HR API integration tests against a real Postgres (skipped w/o DB).

Covers the employee lifecycle (create → read → update → list → status →
terminate), per-tenant employee numbering, tenant isolation of employees and
leave requests, and the leave lifecycle (pro-rata accrual on hire, approval
deduction, over-balance rejection, cancel refund).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .helpers import hire_employee

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient

pytestmark = pytest.mark.integration

ANNUAL_BALANCE_ON_HIRE = 20


async def _annual_balance(client: AsyncClient, headers: dict[str, str], employee_id: str) -> int:
    response = await client.get(
        "/api/v1/hr/leave/balances", params={"employee_id": employee_id}, headers=headers
    )
    assert response.status_code == 200, response.text
    return int({b["leave_type"]: b["balance"] for b in response.json()["data"]}["annual"])


class TestEmployeeLifecycle:
    async def test_create_and_read_employee(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers)

        assert employee["id"]
        assert employee["employee_number"].startswith("EMP-")
        assert employee["first_name"] == "Ada"
        assert employee["employment_status"] == "active"

        response = await client.get(f"/api/v1/hr/employees/{employee['id']}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["id"] == employee["id"]
        assert body["last_name"] == "Lovelace"
        assert body["job_title"] == "Engineer"
        # The detail route enriches with the active compensation.
        assert body["active_compensation"]["amount"] == "5000.00"
        assert body["active_compensation"]["currency"] == "USD"

    async def test_employee_numbers_are_sequential_per_tenant(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        olympus = tenant_headers("olympus")
        first = await hire_employee(client, olympus, first_name="Eve", last_name="One")
        second = await hire_employee(client, olympus, first_name="Eve", last_name="Two")

        first_num = int(first["employee_number"].removeprefix("EMP-"))
        assert int(second["employee_number"].removeprefix("EMP-")) == first_num + 1

        # The globex counter is independent: its first hire starts fresh at the
        # same base instead of continuing olympus's sequence.
        globex = tenant_headers("globex")
        globex_first = await hire_employee(client, globex, first_name="Eve", last_name="Globex")
        assert globex_first["employee_number"] == first["employee_number"]

    async def test_update_employee(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers)

        response = await client.patch(
            f"/api/v1/hr/employees/{employee['id']}",
            json={"job_title": "Senior Engineer"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["job_title"] == "Senior Engineer"

        read = await client.get(f"/api/v1/hr/employees/{employee['id']}", headers=headers)
        assert read.json()["data"]["job_title"] == "Senior Engineer"

    async def test_list_employees_with_filters(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, first_name="Grace", last_name="Hopper")
        await hire_employee(client, headers, first_name="Linus", last_name="Torvalds")

        all_ = await client.get("/api/v1/hr/employees", headers=headers)
        assert all_.status_code == 200, all_.text
        assert len(all_.json()["data"]) == 2

        search = await client.get("/api/v1/hr/employees", params={"q": "torvalds"}, headers=headers)
        assert len(search.json()["data"]) == 1
        assert search.json()["data"][0]["last_name"] == "Torvalds"

    async def test_status_transitions_and_termination(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers, hire_date="2026-01-05")
        employee_id = employee["id"]

        on_leave = await client.post(
            f"/api/v1/hr/employees/{employee_id}/status",
            json={"employment_status": "on_leave"},
            headers=headers,
        )
        assert on_leave.status_code == 200, on_leave.text
        assert on_leave.json()["data"]["employment_status"] == "on_leave"

        back = await client.post(
            f"/api/v1/hr/employees/{employee_id}/status",
            json={"employment_status": "active"},
            headers=headers,
        )
        assert back.json()["data"]["employment_status"] == "active"

        terminated = await client.post(
            f"/api/v1/hr/employees/{employee_id}/terminate",
            json={"termination_date": "2026-08-01", "reason": "redundancy"},
            headers=headers,
        )
        assert terminated.status_code == 200, terminated.text
        assert terminated.json()["data"]["employment_status"] == "terminated"
        assert terminated.json()["data"]["termination_date"] == "2026-08-01"

        # Terminated employees reject further updates (409 employee-terminated).
        update = await client.patch(
            f"/api/v1/hr/employees/{employee_id}",
            json={"job_title": "Nobody"},
            headers=headers,
        )
        assert update.status_code == 409
        assert update.json()["type"].endswith("/employee-terminated")


class TestLeaveLifecycle:
    async def test_balance_accrues_on_hire_and_approval_deducts(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers, hire_date="2026-01-05")
        employee_id = employee["id"]

        # Rule 4: pro-rata accrual for the hire year (hired Jan 5 → 361/365 of 20).
        assert await _annual_balance(client, headers, employee_id) == ANNUAL_BALANCE_ON_HIRE

        created = await client.post(
            "/api/v1/hr/leave/requests",
            json={
                "employee_id": employee_id,
                "leave_type": "annual",
                "start_date": "2026-02-02",
                "end_date": "2026-02-04",
                "reason": "family",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        request_id = created.json()["data"]["id"]
        assert created.json()["data"]["days"] == 3
        assert created.json()["data"]["status"] == "pending"

        approved = await client.post(
            f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "approved"
        assert await _annual_balance(client, headers, employee_id) == ANNUAL_BALANCE_ON_HIRE - 3

    async def test_approve_beyond_balance_is_rejected(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers, hire_date="2026-01-05")

        created = await client.post(
            "/api/v1/hr/leave/requests",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": "2026-02-01",
                "end_date": "2026-03-02",  # 30 days > 20 accrued
            },
            headers=headers,
        )
        request_id = created.json()["data"]["id"]

        approved = await client.post(
            f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers
        )
        assert approved.status_code == 422, approved.text
        assert approved.json()["type"].endswith("/leave-balance-exceeded")
        # Nothing was written: still pending, balance untouched.
        assert await _annual_balance(client, headers, employee["id"]) == ANNUAL_BALANCE_ON_HIRE

    async def test_cancel_approved_request_refunds_balance(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers, hire_date="2026-01-05")
        employee_id = employee["id"]

        created = await client.post(
            "/api/v1/hr/leave/requests",
            json={
                "employee_id": employee_id,
                "leave_type": "annual",
                "start_date": "2026-02-02",
                "end_date": "2026-02-04",
            },
            headers=headers,
        )
        request_id = created.json()["data"]["id"]
        await client.post(f"/api/v1/hr/leave/requests/{request_id}/approve", headers=headers)
        assert await _annual_balance(client, headers, employee_id) == ANNUAL_BALANCE_ON_HIRE - 3

        cancelled = await client.post(
            f"/api/v1/hr/leave/requests/{request_id}/cancel", headers=headers
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["data"]["status"] == "cancelled"
        assert await _annual_balance(client, headers, employee_id) == ANNUAL_BALANCE_ON_HIRE


class TestTenantIsolation:
    async def test_employee_not_visible_across_tenants(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        olympus = tenant_headers("olympus")
        employee = await hire_employee(client, olympus)

        globex = tenant_headers("globex")
        response = await client.get(f"/api/v1/hr/employees/{employee['id']}", headers=globex)
        assert response.status_code == 404

        listing = await client.get("/api/v1/hr/employees", headers=globex)
        assert listing.status_code == 200, listing.text
        assert listing.json()["data"] == []

    async def test_leave_request_not_visible_across_tenants(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        olympus = tenant_headers("olympus")
        employee = await hire_employee(client, olympus, hire_date="2026-01-05")
        created = await client.post(
            "/api/v1/hr/leave/requests",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": "2026-02-02",
                "end_date": "2026-02-04",
            },
            headers=olympus,
        )
        request_id = created.json()["data"]["id"]

        globex = tenant_headers("globex")
        response = await client.get(f"/api/v1/hr/leave/requests/{request_id}", headers=globex)
        assert response.status_code == 404

        listing = await client.get(
            "/api/v1/hr/leave/requests",
            params={"employee_id": employee["id"]},
            headers=globex,
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["data"] == []
