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

    async def _repo_delete(self, tenant_id: str, run_id: str, *, keep: list[str]) -> int:
        from core.db.sequence_repository import SequenceRepository
        from core.db.session import async_session_factory
        from core.features.payroll.repository import PayrollRepository

        async with async_session_factory() as session:
            repo = PayrollRepository(session, next_sequence=SequenceRepository(session).next_value)
            return await repo.delete_entries_for_run(
                uuid.UUID(run_id),
                [uuid.UUID(e) for e in keep],
                tenant_id=uuid.UUID(tenant_id),
            )

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

    async def test_direct_delete_blocked_on_approved_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        from core.core.exceptions import PayrollEntryImmutableError

        headers = tenant_headers("olympus")
        run_id, _entry_id, tenant_id = await self._seed_computed_entry(
            client, headers, integration_db
        )
        approved = await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=headers)
        assert approved.status_code == 200, approved.text

        # Direct repo DELETE (bypassing the service layer) must refuse to drop
        # entries from an immutable run — same defense-in-depth as update_entry.
        with pytest.raises(PayrollEntryImmutableError):
            await self._repo_delete(tenant_id, run_id, keep=[])

    async def test_direct_delete_allowed_on_computed_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        headers = tenant_headers("olympus")
        run_id, _entry_id, tenant_id = await self._seed_computed_entry(
            client, headers, integration_db
        )

        # On a mutable (computed) run the same direct call succeeds and reports
        # the number of stale entries dropped (gap #10 recompute path).
        deleted = await self._repo_delete(tenant_id, run_id, keep=[])
        assert deleted == 1


async def _seed_payroll_accrual_chart(integration_db: dict[str, str]) -> uuid.UUID:
    """Insert the payroll accrual accounts (5010/2010/2020) for the olympus tenant.

    The API integration DB provisions no finance chart by design — tenants only
    get one via the demo seeding script — so JE bridge tests seed the fixture
    tenant's chart explicitly (one of the Commit 4 acceptance criteria).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from core.db.session import async_session_factory
    from core.domain.value_objects import AccountType
    from core.features.finance.models.chart_of_account import ErpChartOfAccountModel

    tenant_id = uuid.UUID(integration_db["acme_id"])
    rows = [
        ("5010", "Salaries Expense", AccountType.EXPENSE),
        ("2010", "Accrued Salaries Payable", AccountType.LIABILITY),
        ("2020", "Payroll Deductions Payable", AccountType.LIABILITY),
    ]
    async with async_session_factory() as session:
        for code, name, account_type in rows:
            await session.execute(
                pg_insert(ErpChartOfAccountModel)
                .values(
                    tenant_id=tenant_id,
                    id=uuid.uuid4(),
                    code=code,
                    name=name,
                    account_type=account_type,
                    is_active=True,
                )
                .on_conflict_do_nothing()
            )
        await session.commit()
    return tenant_id


async def _fetch_payroll_journal_entry(
    tenant_id: uuid.UUID, run_id: str
) -> dict[str, object] | None:
    """The payroll accrual JE (source='payroll', source_ref=run_id), if any."""
    from sqlalchemy import func, select

    from core.db.session import async_session_factory
    from core.features.finance.models.journal_entry import ErpJournalEntryModel
    from core.features.finance.models.journal_line import ErpJournalLineModel

    async with async_session_factory() as session:
        stmt = (
            select(
                ErpJournalEntryModel,
                func.count(ErpJournalLineModel.id).label("line_count"),
            )
            .outerjoin(ErpJournalLineModel)
            .where(
                ErpJournalEntryModel.tenant_id == tenant_id,
                ErpJournalEntryModel.source == "payroll",
                ErpJournalEntryModel.source_ref == run_id,
            )
            .group_by(ErpJournalEntryModel.tenant_id, ErpJournalEntryModel.id)
        )
        row = (await session.execute(stmt)).one_or_none()
        if row is None:
            return None
        entry, line_count = row
        return {
            "entry_id": str(entry.id),
            "status": entry.status.value,
            "line_count": line_count,
        }


class TestJeBridge:
    """Commit 4 — mark-paid handshakes a DRAFT payroll accrual JE into Finance."""

    async def _paid_run(
        self,
        client: AsyncClient,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        await hire_employee(client, headers, hire_date="2026-01-05")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        run_id = run["id"]
        result = await _compute(client, headers, run_id)
        assert len(result["entries"]) == 1
        approved = await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=headers)
        assert approved.status_code == 200, approved.text
        paid = await client.post(f"/api/v1/payroll/runs/{run_id}/pay", headers=headers)
        assert paid.status_code == 200, paid.text
        return cast("dict[str, Any]", paid.json()["data"])

    async def test_mark_paid_drafts_accrual_when_chart_seeded(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        tenant_id = await _seed_payroll_accrual_chart(integration_db)
        headers = tenant_headers("olympus")
        # Non-zero deductions exercise the 3-leg entry (gross = net + deductions).
        response = await client.put(
            "/api/v1/payroll/settings",
            json={"pf_rate": 0.05, "tax_rate": 0.10},
            headers=headers,
        )
        assert response.status_code == 200, response.text

        paid = await self._paid_run(client, headers)

        assert paid["status"] == "paid"
        assert paid["je_bridge_status"] == "draft"
        je = await _fetch_payroll_journal_entry(tenant_id, paid["id"])
        assert je is not None
        assert je["status"] == "draft"
        assert je["line_count"] == 3

    async def test_full_cycle_schedule_to_accrual_draft(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        """HR-AUT-001 full-cycle demo (Gherkin 3) across every deliverable.

        batch computes payslips -> run approved -> payslip-review approve gates
        the employee's ``payslip_ready`` notification (no duplicates) -> paying
        drafts the Finance accrual JE. Chains the previously isolated
        notification orchestrator and JE-bridge paths into one cross-module
        proof.
        """
        from sqlalchemy import text as sa_text

        from core.db.session import async_session_factory

        tenant_id = await _seed_payroll_accrual_chart(integration_db)
        headers = tenant_headers("olympus")

        # Non-zero deductions exercise the 3-leg accrual entry.
        settings_resp = await client.put(
            "/api/v1/payroll/settings",
            json={"pf_rate": 0.05, "tax_rate": 0.10},
            headers=headers,
        )
        assert settings_resp.status_code == 200, settings_resp.text

        # Batch completes -> exactly one computed payslip queued for review.
        employee = await hire_employee(client, headers, hire_date="2026-01-05")
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        run_id = run["id"]
        result = await _compute(client, headers, run_id)
        assert len(result["entries"]) == 1

        # Link a portal user so payroll-review approval gates their delivery.
        linked_user = uuid.uuid4()
        async with async_session_factory() as session:
            await session.execute(
                sa_text(
                    "UPDATE erp_employees SET user_id = :uid "
                    "WHERE id = :eid AND tenant_id = :tid"
                ),
                {"uid": linked_user, "eid": uuid.UUID(employee["id"]), "tid": tenant_id},
            )
            await session.commit()

        approved = await client.post(f"/api/v1/payroll/runs/{run_id}/approve", headers=headers)
        assert approved.status_code == 200, approved.text

        # Approval releases the employee's payslip_ready notification (0030).
        reviews_resp = await client.get("/api/v1/payroll/payslips/reviews", headers=headers)
        assert reviews_resp.status_code == 200, reviews_resp.text
        reviews = reviews_resp.json()["data"]
        assert len(reviews) == 1
        review_id = reviews[0]["id"]
        approve_resp = await client.post(
            f"/api/v1/payroll/payslips/reviews/{review_id}/approve", headers=headers
        )
        assert approve_resp.status_code == 200, approve_resp.text
        assert approve_resp.json()["data"]["status"] == "approved"

        async with async_session_factory() as session:
            count = (
                await session.execute(
                    sa_text(
                        "SELECT count(*) FROM ai_payroll_notifications "
                        "WHERE tenant_id = :tid AND recipient_user_id = :uid "
                        "AND event_type = 'payslip_ready'"
                    ),
                    {"tid": tenant_id, "uid": linked_user},
                )
            ).scalar_one()
            assert count == 1  # exactly one: the dedupe key prevents re-delivery

        # Mark-paid cross-module bridge -> accrual JE draft appears in Finance.
        paid = await client.post(f"/api/v1/payroll/runs/{run_id}/pay", headers=headers)
        assert paid.status_code == 200, paid.text
        paid_data = paid.json()["data"]
        assert paid_data["status"] == "paid"
        assert paid_data["je_bridge_status"] == "draft"
        je = await _fetch_payroll_journal_entry(tenant_id, run_id)
        assert je is not None
        assert je["status"] == "draft"
        assert je["line_count"] == 3

    async def test_mark_paid_pending_when_chart_missing(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        tenant_id = uuid.UUID(integration_db["acme_id"])

        paid = await self._paid_run(client, tenant_headers("olympus"))

        # No chart in the API integration DB → paid succeeds but no JE is
        # drafted; the run exposes the queryable pending state (FIN-AI-001).
        assert paid["status"] == "paid"
        assert paid["je_bridge_status"] == "pending"
        assert await _fetch_payroll_journal_entry(tenant_id, paid["id"]) is None

    async def test_mark_paid_no_bridge_when_flag_disabled(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
        integration_db: dict[str, str],
    ) -> None:
        tenant_id = await _seed_payroll_accrual_chart(integration_db)
        headers = tenant_headers("olympus")
        response = await client.put(
            "/api/v1/payroll/settings",
            json={"je_bridge_enabled": False},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["je_bridge_enabled"] is False

        paid = await self._paid_run(client, headers)

        assert paid["status"] == "paid"
        assert paid["je_bridge_status"] == "none"
        assert await _fetch_payroll_journal_entry(tenant_id, paid["id"]) is None


class TestRunPayslips:
    async def test_payslips_endpoint_returns_employee_rows(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        await hire_employee(client, headers, hire_date="2026-01-01", monthly_salary="4000.00")
        await hire_employee(
            client,
            headers,
            first_name="Grace",
            last_name="Hopper",
            hire_date="2026-01-01",
            monthly_salary="6000.00",
        )
        run = await create_payroll_run(client, headers, "2026-01-01", "2026-01-31")
        run_id = run["id"]
        result = await _compute(client, headers, run_id)
        assert len(result["entries"]) == 2

        response = await client.get(f"/api/v1/payroll/runs/{run_id}/payslips", headers=headers)
        assert response.status_code == 200, response.text
        payslips = response.json()["data"]
        assert len(payslips) == 2
        assert [p["employee_name"] for p in payslips] == [
            "Ada Lovelace",
            "Grace Hopper",
        ]
        assert payslips[0]["gross"]["amount"] == "4000.00"
        assert payslips[0]["deductions"]["amount"] == "0.00"
        assert payslips[0]["net"]["amount"] == "4000.00"

    async def test_payslips_endpoint_empty_on_draft_run(
        self,
        client: AsyncClient,
        tenant_headers: Callable[[str], dict[str, str]],
        seeded_hr_defaults: None,
    ) -> None:
        headers = tenant_headers("olympus")
        run = await create_payroll_run(client, headers, "2026-02-01", "2026-02-28")
        response = await client.get(f"/api/v1/payroll/runs/{run['id']}/payslips", headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["data"] == []
