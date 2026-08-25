"""End-to-end HR API integration tests against a real Postgres (skipped w/o DB).

Covers the employee lifecycle (create → read → update → list → status →
terminate), per-tenant employee numbering, tenant isolation of employees and
leave requests, and the leave lifecycle (pro-rata accrual on hire, approval
deduction, over-balance rejection, cancel refund).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import pytest

from .helpers import hire_employee

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient


def _future(days_offset: int = 1) -> str:
    """Return a future ISO date string for use in leave-request tests."""
    return (date.today() + timedelta(days=days_offset)).isoformat()

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

    async def test_list_employees_orders_newest_hire_first(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, first_name="Old", last_name="Timer", hire_date="2024-06-01")
        await hire_employee(client, headers, first_name="New", last_name="Blood", hire_date="2026-03-15")
        await hire_employee(client, headers, first_name="Mid", last_name="Way", hire_date="2025-01-10")

        response = await client.get("/api/v1/hr/employees", headers=headers)
        assert response.status_code == 200, response.text
        # Newest hire first regardless of creation order.
        assert [e["hire_date"] for e in response.json()["data"]] == [
            "2026-03-15",
            "2025-01-10",
            "2024-06-01",
        ]

    async def test_terminated_list_orders_latest_termination_first(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        early = await hire_employee(client, headers, first_name="Bea", last_name="Early", hire_date="2025-01-05")
        late = await hire_employee(client, headers, first_name="Bea", last_name="Late", hire_date="2025-02-05")

        for employee_id, termination_date in (
            (early["id"], "2026-08-01"),
            (late["id"], "2026-09-15"),
        ):
            response = await client.post(
                f"/api/v1/hr/employees/{employee_id}/terminate",
                json={"termination_date": termination_date, "reason": "redundancy"},
                headers=headers,
            )
            assert response.status_code == 200, response.text

        listed = await client.get(
            "/api/v1/hr/employees", params={"status": "terminated"}, headers=headers
        )
        assert listed.status_code == 200, listed.text
        rows = listed.json()["data"]
        assert [e["termination_date"] for e in rows] == ["2026-09-15", "2026-08-01"]

    async def test_list_employees_includes_active_compensation(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, first_name="Grace", last_name="Hopper")

        all_ = await client.get("/api/v1/hr/employees", headers=headers)
        assert all_.status_code == 200, all_.text
        listed = {e["last_name"]: e for e in all_.json()["data"]}
        assert listed["Hopper"]["active_compensation"]["amount"] == "5000.00"
        assert listed["Hopper"]["active_compensation"]["currency"] == "USD"

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

    async def test_list_employees_accepts_comma_separated_statuses(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        """``status=active,on_leave`` must exclude terminated rows so the web
        "All statuses" view can hide terminated employees server-side."""
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, first_name="Ada", last_name="Keeper")
        on_leave = await hire_employee(client, headers, first_name="Grace", last_name="Away")
        await client.post(
            f"/api/v1/hr/employees/{on_leave['id']}/status",
            json={"employment_status": "on_leave"},
            headers=headers,
        )
        gone = await hire_employee(client, headers, first_name="Alan", last_name="Gone")
        terminated = await client.post(
            f"/api/v1/hr/employees/{gone['id']}/terminate",
            json={"termination_date": "2026-08-01"},
            headers=headers,
        )
        assert terminated.status_code == 200, terminated.text

        not_terminated = await client.get(
            "/api/v1/hr/employees",
            params={"status": "active,on_leave"},
            headers=headers,
        )
        assert not_terminated.status_code == 200, not_terminated.text
        last_names = {e["last_name"] for e in not_terminated.json()["data"]}
        assert last_names == {"Keeper", "Away"}

        only_active = await client.get(
            "/api/v1/hr/employees",
            params={"status": "active"},
            headers=headers,
        )
        assert {e["last_name"] for e in only_active.json()["data"]} == {"Keeper"}

        only_terminated = await client.get(
            "/api/v1/hr/employees",
            params={"status": "terminated"},
            headers=headers,
        )
        assert {e["last_name"] for e in only_terminated.json()["data"]} == {"Gone"}
        assert only_terminated.json()["data"][0]["termination_date"] == "2026-08-01"

        bad = await client.get(
            "/api/v1/hr/employees",
            params={"status": "active,fired"},
            headers=headers,
        )
        assert bad.status_code == 422

        # A whitespace variant of the same set resolves identically.
        spaced = await client.get(
            "/api/v1/hr/employees",
            params={"status": " active , on_leave "},
            headers=headers,
        )
        assert {e["last_name"] for e in spaced.json()["data"]} == {"Keeper", "Away"}


class TestEmployeeCreateValidation:
    """EmployeeCreate requires first/last name, email, and phone (422 otherwise)."""

    async def _post(self, client: AsyncClient, headers: dict[str, str], payload: dict) -> None:
        return await client.post("/api/v1/hr/employees", json=payload, headers=headers)

    async def test_missing_email_is_rejected(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        response = await self._post(
            client,
            headers,
            {
                "first_name": "No",
                "last_name": "Email",
                "job_title": "Engineer",
                "hire_date": "2026-01-05",
                "phone": "+1 555 010 0000",
            },
        )
        assert response.status_code == 422
        assert any(
            issue["loc"][-1] == "email" for issue in response.json()["errors"]
        ), response.text

    async def test_malformed_email_is_rejected(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        response = await self._post(
            client,
            headers,
            {
                "first_name": "Bad",
                "last_name": "Email",
                "job_title": "Engineer",
                "hire_date": "2026-01-05",
                "email": "not-an-email",
                "phone": "+1 555 010 0000",
            },
        )
        assert response.status_code == 422
        assert any(
            issue["loc"][-1] == "email" for issue in response.json()["errors"]
        ), response.text

    async def test_missing_phone_is_rejected(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        response = await self._post(
            client,
            headers,
            {
                "first_name": "No",
                "last_name": "Phone",
                "job_title": "Engineer",
                "hire_date": "2026-01-05",
                "email": "no.phone@example.com",
            },
        )
        assert response.status_code == 422
        assert any(
            issue["loc"][-1] == "phone" for issue in response.json()["errors"]
        ), response.text

    async def test_blank_fields_are_rejected_after_strip(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        response = await self._post(
            client,
            headers,
            {
                "first_name": "   ",
                "last_name": "Blank",
                "job_title": "Engineer",
                "hire_date": "2026-01-05",
                "email": "blank@example.com",
                "phone": "   ",
            },
        )
        assert response.status_code == 422
        locations = {issue["loc"][-1] for issue in response.json()["errors"]}
        assert "first_name" in locations
        assert "phone" in locations


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
                "start_date": _future(1),
                "end_date": _future(3),
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
                "start_date": _future(1),
                "end_date": _future(30),  # 30 days > 20 accrued
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
                "start_date": _future(1),
                "end_date": _future(3),
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


class TestAttendanceLifecycle:
    async def test_upsert_creates_then_corrects_same_day(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers)

        created = await client.put(
            "/api/v1/hr/attendance",
            json={
                "employee_id": employee["id"],
                "work_date": "2026-07-01",
                "status": "late",
                "note": "traffic",
            },
            headers=headers,
        )
        assert created.status_code == 200, created.text
        body = created.json()["data"]
        # Late arrival -> half pay, derived server-side.
        assert body["status"] == "late"
        assert body["pay_impact"] == "half"
        record_id = body["id"]

        corrected = await client.put(
            "/api/v1/hr/attendance",
            json={
                "employee_id": employee["id"],
                "work_date": "2026-07-01",
                "status": "on_time",
            },
            headers=headers,
        )
        assert corrected.status_code == 200, corrected.text
        fixed = corrected.json()["data"]
        assert fixed["id"] == record_id  # same day upserted, not duplicated
        assert fixed["status"] == "on_time"
        assert fixed["pay_impact"] == "full"

        listed = await client.get(
            "/api/v1/hr/attendance",
            params={
                "employee_id": employee["id"],
                "date_from": "2026-07-01",
                "date_to": "2026-07-01",
            },
            headers=headers,
        )
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["data"]) == 1
        assert listed.json()["data"][0]["pay_impact"] == "full"

    async def test_list_filters_and_joins_employee_fields(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        ada = await hire_employee(client, headers)
        grace = await hire_employee(client, headers, first_name="Grace", last_name="Hopper")

        for employee_id, day, status in (
            (ada["id"], "2026-07-01", "late"),
            (ada["id"], "2026-07-02", "absent"),
            (grace["id"], "2026-07-01", "on_time"),
        ):
            response = await client.put(
                "/api/v1/hr/attendance",
                json={"employee_id": employee_id, "work_date": day, "status": status},
                headers=headers,
            )
            assert response.status_code == 200, response.text

        late_only = await client.get(
            "/api/v1/hr/attendance",
            params={"employee_id": ada["id"], "status": "late"},
            headers=headers,
        )
        assert late_only.status_code == 200, late_only.text
        rows = late_only.json()["data"]
        assert len(rows) == 1
        assert rows[0]["work_date"] == "2026-07-01"
        assert rows[0]["pay_impact"] == "half"

        per_employee = await client.get(
            f"/api/v1/hr/employees/{ada['id']}/attendance", headers=headers
        )
        assert per_employee.status_code == 200, per_employee.text
        days = [r["work_date"] for r in per_employee.json()["data"]]
        assert days == ["2026-07-02", "2026-07-01"]  # newest work date first

    async def test_absent_maps_to_no_pay(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers)
        response = await client.put(
            "/api/v1/hr/attendance",
            json={
                "employee_id": employee["id"],
                "work_date": "2026-07-03",
                "status": "absent",
                "note": "unexcused",
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["pay_impact"] == "none"

    async def test_unknown_employee_is_404(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        response = await client.put(
            "/api/v1/hr/attendance",
            json={
                "employee_id": "00000000-0000-0000-0000-000000000000",
                "work_date": "2026-07-01",
                "status": "on_time",
            },
            headers=headers,
        )
        assert response.status_code == 404, response.text
        assert response.json()["type"].endswith("/not-found")


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
                "start_date": _future(1),
                "end_date": _future(3),
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

    async def test_attendance_not_visible_across_tenants(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        olympus = tenant_headers("olympus")
        employee = await hire_employee(client, olympus)
        created = await client.put(
            "/api/v1/hr/attendance",
            json={"employee_id": employee["id"], "work_date": "2026-07-01", "status": "late"},
            headers=olympus,
        )
        assert created.status_code == 200, created.text

        globex = tenant_headers("globex")
        listing = await client.get(
            "/api/v1/hr/attendance",
            params={"employee_id": employee["id"]},
            headers=globex,
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["data"] == []

        # Cross-tenant upsert is rejected by the composite FK probe (404).
        cross_write = await client.put(
            "/api/v1/hr/attendance",
            json={"employee_id": employee["id"], "work_date": "2026-07-02", "status": "late"},
            headers=globex,
        )
        assert cross_write.status_code == 404
