"""Payroll repository and integration ports — persistence + cross-feature contracts.

The consumer of leave data declares ``LeaveLedgerPort`` (docs/hr-payroll.md §6
Step 3 — implemented by ``features/hr``, injected at the composition root in
``api/deps.py``). Neither feature imports the other's repository or models.
Payroll reads the active-employee roster through ``PayrollRepositoryPort``
(its one sanctioned cross-feature read, per the ERD: ``PayrollEntryModel.
employee_id -> erp_employees``).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Protocol

from core.domain import entities as ent
from core.domain.value_objects import Money


class LeaveLedgerPort(Protocol):
    """Leave reads + annual accrual — implemented by ``features/hr``.

    Used by payroll to compute the unpaid-leave overlap for ``pay_days``
    proration (docs/hr-payroll.md §4.10, Rule 9) and to run the Rule 4 annual
    accrual at the start of every compute (gap #3).
    """

    async def approved_unpaid_days(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> int:
        """Return the count of approved ``unpaid`` leave days overlapping the period."""
        ...

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID) -> Sequence[str]:
        """Return leave-type names that accrue annually (``accrues`` = true)."""
        ...

    async def accrue(
        self,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        leave_type: str,
        year: int,
        actor_user_id: uuid.UUID | None = None,
    ) -> object | None:
        """Write the idempotent annual leave accrual for one employee/type/year."""
        ...


class PayrollRepositoryPort(Protocol):
    """Persistence contract for compensation, runs, entries, settings, roster."""

    # --- Compensation ---
    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation: ...

    async def get_compensation(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        effective_for: date,
    ) -> ent.Compensation | None: ...

    async def list_compensation(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.Compensation]: ...

    # --- Runs ---
    async def create_run(self, run: ent.PayrollRun) -> ent.PayrollRun: ...

    async def get_run(self, run_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.PayrollRun | None: ...

    async def list_runs(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ent.PayrollRun]: ...

    async def find_overlapping_run(
        self,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> ent.PayrollRun | None: ...

    async def transition_run_status(
        self,
        run_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        tenant_id: uuid.UUID,
        computed_by: uuid.UUID | None = None,
        approved_by: uuid.UUID | None = None,
        paid_by: uuid.UUID | None = None,
        computed_at: object | None = None,
        approved_at: object | None = None,
        paid_at: object | None = None,
        void_reason: str | None = None,
        total_gross: Money | None = None,
        total_net: Money | None = None,
        skipped_employees: list[dict[str, str]] | None = None,
    ) -> ent.PayrollRun | None: ...

    async def next_run_code(self, tenant_id: uuid.UUID) -> int: ...

    # --- Entries ---
    async def upsert_entries(
        self, entries: Sequence[ent.PayrollEntry], *, tenant_id: uuid.UUID
    ) -> None: ...

    async def list_entries(
        self, run_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.PayrollEntry]: ...

    async def get_entry(
        self, run_id: uuid.UUID, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollEntry | None: ...

    async def get_entry_by_id(
        self, entry_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollEntry | None: ...

    async def update_entry(self, entry: ent.PayrollEntry) -> ent.PayrollEntry: ...

    async def delete_entries_for_run(
        self,
        run_id: uuid.UUID,
        employee_ids: Sequence[uuid.UUID],
        *,
        tenant_id: uuid.UUID,
    ) -> int:
        """Delete run entries whose employee is NOT in ``employee_ids`` (recompute cleanup)."""
        ...

    # --- Settings ---
    async def get_settings(self, tenant_id: uuid.UUID) -> ent.PayrollSettings | None: ...

    async def upsert_settings(self, settings: ent.PayrollSettings) -> ent.PayrollSettings: ...

    # --- Roster (read-only, one-way erp_employees read per the ERD) ---
    async def list_active_employees(
        self,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> Sequence[ent.Employee]: ...


__all__ = ["LeaveLedgerPort", "PayrollRepositoryPort"]
