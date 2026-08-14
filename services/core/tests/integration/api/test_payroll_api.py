"""End-to-end payroll API integration tests against a real Postgres (skipped w/o DB).

Covers settings defaults/update, compensation history + active pick, the run
lifecycle (create → compute → approve → pay), Rule 9 pay-day/gross arithmetic,
Rule 10 period-overlap conflicts (and re-create after void), skip behaviour for
employees without compensation, compute idempotence, entry immutability after
approval, and tenant isolation.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest

from .helpers import create_payroll_run, hire_employee

if TYPE_CHECKING:
    from collections.abc import Callable

    from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def _compute(
    client: AsyncClient,
    headers: dict[str, str],
    run_id: str,
) -> dict[str, Any]:
    response = await client.post(f"/api/v1/payroll/runs/{run_id}/compute", headers=headers)
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json()["data"])


class TestSettings:
    async def test_seeded_defaults(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        response = await client.get("/api/v1/payroll/settings", headers=tenant_headers("olympus"))
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["default_currency"] == "USD"
        assert body["pf_rate"] == "0"
        assert body["tax_rate"] == "0"
        assert body["rounding"] == "nearest"

    async def test_update_settings(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        response = await client.put(
            "/api/v1/payroll/settings",
            json={"pf_rate": 0.05, "tax_rate": 0.10, "rounding": "up"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()["data"]
        assert body["pf_rate"] == "0.05"
        assert body["tax_rate"] == "0.10"
        assert body["rounding"] == "up"

        read = await client.get("/api/v1/payroll/settings", headers=headers)
        assert read.json()["data"]["rounding"] == "up"


class TestCompensation:
    async def test_history_and_active_compensation(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers)

        raise_response = await client.post(
            "/api/v1/payroll/compensation",
            json={
                "employee_id": employee["id"],
                "effective_from": "2026-06-01",
                "monthly_salary": "6000.00",
            },
            headers=headers,
        )
        assert raise_response.status_code == 201, raise_response.text

        history = await client.get(
            "/api/v1/payroll/compensation",
            params={"employee_id": employee["id"]},
            headers=headers,
        )
        assert history.status_code == 200, history.text
        entries = history.json()["data"]
        assert len(entries) == 2
        assert entries[0]["monthly_salary"]["amount"] == "6000.00"  # newest first
        assert entries[1]["monthly_salary"]["amount"] == "5000.00"

        detail = await client.get(f"/api/v1/hr/employees/{employee['id']}", headers=headers)
        assert detail.json()["data"]["active_compensation"]["amount"] == "6000.00"

    async def test_compensation_is_tenant_scoped(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        olympus = tenant_headers("olympus")
        employee = await hire_employee(client, olympus)

        globex = tenant_headers("globex")
        history = await client.get(
            "/api/v1/payroll/compensation",
            params={"employee_id": employee["id"]},
            headers=globex,
        )
        assert history.status_code == 200, history.text
        assert history.json()["data"] == []


class TestRunLifecycle:
    async def test_compute_pay_days_and_amounts(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        # Hired Jan 5 → Jan 2026 run pays 27 of 31 days at 5000/month.
        employee = await hire_employee(client, headers, hire_date="2026-01-05")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        run_id = run["id"]
        assert run["status"] == "draft"

        result = await _compute(client, headers, run_id)
        assert result["run"]["status"] == "computed"
        assert result["skipped"] == []
        assert len(result["entries"]) == 1

        entry = result["entries"][0]
        assert entry["employee_id"] == employee["id"]
        assert entry["pay_days"] == 27
        assert entry["base_salary"]["amount"] == "5000.00"
        assert entry["gross"]["amount"] == "4354.84"
        assert entry["deductions"]["amount"] == "0.00"
        assert entry["net"]["amount"] == "4354.84"

        assert result["run"]["total_gross"]["amount"] == "4354.84"
        assert result["run"]["total_net"]["amount"] == "4354.84"

    async def test_employee_without_compensation_is_skipped(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        employee = await hire_employee(client, headers, monthly_salary=None)
        run = await create_payroll_run(client, headers, "2026-02-01", "2026-02-28")

        result = await _compute(client, headers, run["id"])
        assert result["entries"] == []
        assert len(result["skipped"]) == 1
        assert result["skipped"][0]["employee_id"] == employee["id"]
        assert result["skipped"][0]["reason"] == "no effective compensation"
        assert result["run"]["total_gross"]["amount"] == "0.00"

    async def test_recompute_is_idempotent(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, hire_date="2026-01-05")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")

        first = await _compute(client, headers, run["id"])
        second = await _compute(client, headers, run["id"])
        assert second["run"]["status"] == "computed"
        assert second["run"]["total_net"] == first["run"]["total_net"]
        assert len(second["entries"]) == 1

    async def test_overlapping_period_conflict_and_recreate_after_void(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")

        conflict = await client.post(
            "/api/v1/payroll/runs",
            json={"period_start": "2026-01-15", "period_end": "2026-02-15"},
            headers=headers,
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["type"].endswith("/payroll-period-conflict")

        voided = await client.post(f"/api/v1/payroll/runs/{run['id']}/void", headers=headers)
        assert voided.status_code == 200, voided.text
        assert voided.json()["data"]["status"] == "void"

        # A voided run no longer blocks the period (Rule 10 excludes void).
        recreated = await create_payroll_run(client, headers, "2026-01-15", "2026-02-15")
        assert recreated["status"] == "draft"

    async def test_approve_pay_and_entry_immutability(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, hire_date="2026-01-05")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        run_id = run["id"]

        result = await _compute(client, headers, run_id)
        entry_id = result["entries"][0]["id"]

        approved = await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["status"] == "approved"

        paid = await client.post(f"/api/v1/payroll/runs/{run_id}/pay", headers=headers)
        assert paid.status_code == 200, paid.text
        assert paid.json()["data"]["status"] == "paid"

        # Rule 8: entries are immutable once a run is approved.
        adjusted = await client.patch(
            f"/api/v1/payroll/runs/{run_id}/entries/{entry_id}",
            json={"adjustments": {"amount": "100.00"}},
            headers=headers,
        )
        assert adjusted.status_code == 409, adjusted.text
        assert adjusted.json()["type"].endswith("/payroll-entry-immutable")

    async def test_run_not_visible_across_tenants(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        olympus = tenant_headers("olympus")
        run = await create_payroll_run(client, olympus, "2026-01-01", "2026-01-31")

        globex = tenant_headers("globex")
        response = await client.get(f"/api/v1/payroll/runs/{run['id']}", headers=globex)
        assert response.status_code == 404


class TestRosterScope:
    """Rule 9 roster scope against the REAL repository SQL (docs §4.9).

    Exercises ``PayrollRepository.list_active_employees`` end-to-end through a
    compute: an employee terminated mid-period stays on the roster and is paid
    through the termination date; employees terminated before ``period_start``
    or hired after ``period_end`` are excluded entirely.
    """

    async def test_terminated_mid_period_included_and_others_excluded(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")

        # Terminated DURING the period: hired Jan 1, terminated Jan 15. Must be
        # on the roster and paid through the termination date (15 of 31 days).
        mid = await hire_employee(client, headers, hire_date="2026-01-01")
        terminated = await client.post(
            f"/api/v1/hr/employees/{mid['id']}/terminate",
            json={"termination_date": "2026-01-15"},
            headers=headers,
        )
        assert terminated.status_code == 200, terminated.text

        # Terminated BEFORE period_start: never on the Jan roster.
        before = await hire_employee(client, headers, hire_date="2025-06-01")
        terminated = await client.post(
            f"/api/v1/hr/employees/{before['id']}/terminate",
            json={"termination_date": "2025-12-15"},
            headers=headers,
        )
        assert terminated.status_code == 200, terminated.text

        # Hired AFTER period_end: never on the Jan roster.
        after = await hire_employee(client, headers, hire_date="2026-02-01")

        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        result = await _compute(client, headers, run["id"])

        # Only the mid-period employee is on the roster — and they are paid
        # through their termination date, not the full period.
        assert len(result["entries"]) == 1
        entry = result["entries"][0]
        assert entry["employee_id"] == mid["id"]
        assert entry["employee_id"] != before["id"]
        assert entry["employee_id"] != after["id"]
        assert entry["pay_days"] == 15
        assert entry["gross"]["amount"] == "2419.35"  # 5000 x 15/31, rounded nearest

        # The excluded employees are not even recorded as skipped (skipped is
        # only for roster employees without effective compensation/pay days).
        assert result["skipped"] == []


class TestRepositoryLevelEntryImmutability:
    """Rule 8 defense-in-depth (Task 3 gap #2).

    Calls ``PayrollRepository.update_entry`` DIRECTLY against the real
    repository, bypassing the service layer, on entries belonging to runs in
    every status — proving the repository-level backstop itself fires when
    something ever bypasses the service guard.
    """

    async def _repo_update(
        self,
        tenant_id: str,
        entry_id: str,
        *,
        adjustments: dict[str, Any],
    ) -> dict[str, Any]:
        from core.db.sequence_repository import SequenceRepository
        from core.db.session import async_session_factory
        from core.features.payroll.repository import PayrollRepository

        async with async_session_factory() as session:
            repo = PayrollRepository(session, next_sequence=SequenceRepository(session).next_value)
            entry = await repo.get_entry_by_id(uuid.UUID(entry_id), tenant_id=uuid.UUID(tenant_id))
            assert entry is not None
            mutated = dataclasses.replace(entry, adjustments=adjustments)
            updated = await repo.update_entry(mutated)
            assert updated.id is not None
            return {"id": str(updated.id), "adjustments": updated.adjustments}

    async def _seed_computed_entry(
        self,
        client: AsyncClient,
        headers: dict[str, str],
        integration_db: dict[str, str],
    ) -> tuple[str, str, str]:
        await hire_employee(client, headers, hire_date="2026-01-05")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        result = await _compute(client, headers, run["id"])
        return run["id"], result["entries"][0]["id"], integration_db["acme_id"]

    async def test_direct_update_blocked_on_approved_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        from core.core.exceptions import PayrollEntryImmutableError

        headers = tenant_headers("olympus")
        run_id, entry_id, tenant_id = await self._seed_computed_entry(
            client, headers, integration_db
        )
        approved = await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=headers)
        assert approved.status_code == 200, approved.text

        with pytest.raises(PayrollEntryImmutableError):
            await self._repo_update(tenant_id, entry_id, adjustments={"amount": "100.00"})

    async def test_direct_update_blocked_on_paid_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        from core.core.exceptions import PayrollEntryImmutableError

        headers = tenant_headers("olympus")
        run_id, entry_id, tenant_id = await self._seed_computed_entry(
            client, headers, integration_db
        )
        approved = await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        paid = await client.post(f"/api/v1/payroll/runs/{run_id}/pay", headers=headers)
        assert paid.status_code == 200, paid.text

        with pytest.raises(PayrollEntryImmutableError):
            await self._repo_update(tenant_id, entry_id, adjustments={"amount": "100.00"})

    async def test_direct_update_blocked_on_voided_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        from core.core.exceptions import PayrollEntryImmutableError

        headers = tenant_headers("olympus")
        run_id, entry_id, tenant_id = await self._seed_computed_entry(
            client, headers, integration_db
        )
        voided = await client.post(f"/api/v1/payroll/runs/{run_id}/void", headers=headers)
        assert voided.status_code == 200, voided.text

        with pytest.raises(PayrollEntryImmutableError):
            await self._repo_update(tenant_id, entry_id, adjustments={"amount": "100.00"})

    async def test_direct_update_allowed_on_computed_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        headers = tenant_headers("olympus")
        _run_id, entry_id, tenant_id = await self._seed_computed_entry(
            client, headers, integration_db
        )

        updated = await self._repo_update(tenant_id, entry_id, adjustments={"amount": "100.00"})
        assert updated["adjustments"] == {"amount": "100.00"}
