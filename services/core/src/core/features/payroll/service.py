"""Payroll service — rules 7-10 (docs/hr-payroll.md §4.9-§4.10) + compute engine.

Payroll is the money-sensitive core of this phase: ``PayrollCompute`` is pure
(no DB), and ``PayrollService`` composes it with the repository, the shared
:class:`AuditService`, and the cross-feature :class:`LeaveLedgerPort`.
Concurrency (atomic conditional UPDATE, RLS, btree_gist exclusion) stays in
the deferred integration suite.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from core.core import audit_events
from core.core.audit_service import AuditService
from core.core.constants import PayrollRounding, PayrollRunStatus
from core.core.exceptions import (
    IllegalStateTransitionError,
    PayrollEntryImmutableError,
    PayrollPeriodConflictError,
)
from core.core.state_machine import InvalidTransitionError, StateMachine
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.events.producers.payroll_events import (
    emit_compensation_recorded,
    emit_entry_adjusted,
    emit_run_approved,
    emit_run_computed,
    emit_run_created,
    emit_run_paid,
    emit_run_voided,
    emit_settings_updated,
)
from core.features.payroll.ports import LeaveLedgerPort, PayrollRepositoryPort

# Run lifecycle (docs §3.3 / §4.10): draft -> computed -> approved -> paid;
# void allowed from draft/computed/approved, NEVER from paid. Recompute is
# idempotent, so computed -> computed is allowed (overwrites entries).
_RUN_MACHINE = StateMachine(
    {
        PayrollRunStatus.DRAFT: (PayrollRunStatus.COMPUTED, PayrollRunStatus.VOID),
        PayrollRunStatus.COMPUTED: (
            PayrollRunStatus.COMPUTED,
            PayrollRunStatus.APPROVED,
            PayrollRunStatus.VOID,
        ),
        PayrollRunStatus.APPROVED: (PayrollRunStatus.PAID, PayrollRunStatus.VOID),
        PayrollRunStatus.PAID: (),
        PayrollRunStatus.VOID: (),
    },
    entity="payroll run",
)


def _require_id(entity: ent.Employee, what: str) -> uuid.UUID:
    """Return a persisted entity's id, which must always be set."""
    if entity.id is None:
        raise ValueError(f"persisted {what} is missing an id")
    return entity.id


def _overlap_days(start_a: date, end_a: date, start_b: date, end_b: date) -> int:
    """Number of days the two inclusive ranges overlap (never negative)."""
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    overlap = (earliest_end - latest_start).days + 1
    return max(overlap, 0)


@dataclasses.dataclass(frozen=True)
class ComputeResult:
    """Outcome of a compute run: the updated run, its entries, and skipped employees."""

    run: ent.PayrollRun
    entries: list[ent.PayrollEntry]
    skipped: list[tuple[uuid.UUID, str]]


class PayrollCompute:
    """Pure payroll computation — no repository, no DB.

    ``pay_days`` follows docs §4.10 Rule 9:
        pay_days = days_in_period
                 - overlap(hire_date, period)
                 - overlap(termination_date, period)
                 - unpaid_leave_overlap
    ``sick``/``annual`` leave never reduce pay. ``net``:
        net = gross - pf_rate*gross - tax_rate*gross - adjustments
    amounts round per the run's settings (nearest/up/down).
    """

    @staticmethod
    def pay_days(
        *,
        period_start: date,
        period_end: date,
        hire_date: date | None = None,
        termination_date: date | None = None,
        unpaid_days: int = 0,
    ) -> int:
        """Full-time-equivalent paid days for one employee in the period.

        Rule 9: ``days_in_period`` minus the period days before hire, after
        termination, and on approved unpaid leave — never negative.
        """
        days_in_period = (period_end - period_start).days + 1
        reduction = 0
        if hire_date is not None and hire_date > period_start:
            reduction += _overlap_days(
                period_start, period_end, period_start, hire_date - timedelta(days=1)
            )
        if termination_date is not None and termination_date < period_end:
            reduction += _overlap_days(
                period_start, period_end, termination_date + timedelta(days=1), period_end
            )
        reduction += max(unpaid_days, 0)
        return max(days_in_period - reduction, 0)

    @staticmethod
    def _round(money: Money, rounding: PayrollRounding) -> Money:
        mode = {
            PayrollRounding.NEAREST: ROUND_HALF_UP,
            PayrollRounding.UP: ROUND_CEILING,
            PayrollRounding.DOWN: ROUND_FLOOR,
        }[rounding]
        return money.rounded(rounding=mode)

    @classmethod
    def compute_entry(
        cls,
        *,
        base_salary: Money,
        pay_days: int,
        days_in_period: int,
        pf_rate: Decimal,
        tax_rate: Decimal,
        rounding: PayrollRounding,
        adjustments: dict[str, object] | None = None,
    ) -> tuple[Money, Money, Money]:
        """Return ``(gross, deductions, net)`` for one employee entry.

        ``gross = base_salary * pay_days / days_in_period``; statutory
        deductions (``pf = pf_rate*gross``, ``tax = tax_rate*gross``) are flat
        percentages; ``adjustments`` is the flat bonus/other net adjustment.
        """
        if days_in_period <= 0:
            raise ValueError("days_in_period must be positive")
        if pay_days < 0:
            raise ValueError("pay_days cannot be negative")
        gross = cls._round(base_salary * Decimal(pay_days) / Decimal(days_in_period), rounding)
        pf = cls._round(gross * pf_rate, rounding)
        tax = cls._round(gross * tax_rate, rounding)
        adj_raw = Decimal(str((adjustments or {}).get("amount", 0)))
        adj = Money(amount=adj_raw, currency=base_salary.currency).rounded(rounding=ROUND_HALF_UP)
        net = cls._round(gross - pf - tax - adj, rounding)
        return gross, pf + tax + adj, net

    @classmethod
    def compute_totals(cls, entries: list[ent.PayrollEntry]) -> tuple[Money, Money]:
        """Sum gross/net across entries for the run's totals (same currency)."""
        if not entries:
            raise ValueError("cannot compute totals for an empty run")
        currency = entries[0].gross.currency
        total_gross = sum((e.gross for e in entries), Money(Decimal("0"), currency))
        total_net = sum((e.net for e in entries), Money(Decimal("0"), currency))
        return total_gross, total_net


class PayrollService:
    """Rules 7-10 orchestration + run/entry/settings lifecycle."""

    def __init__(
        self,
        repository: PayrollRepositoryPort,
        leave_ledger: LeaveLedgerPort,
        audit: AuditService,
    ) -> None:
        self._repo = repository
        self._leave_ledger = leave_ledger
        self._audit = audit

    @property
    def repository(self) -> PayrollRepositoryPort:
        return self._repo

    # ------------------------------------------------------------------
    # Settings (Rule 9 inputs: pf/tax rates, rounding, default currency)
    # ------------------------------------------------------------------
    async def get_settings(self, tenant_id: uuid.UUID) -> ent.PayrollSettings | None:
        return await self._repo.get_settings(tenant_id)

    async def update_settings(
        self,
        settings: ent.PayrollSettings,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollSettings:
        existing = await self._repo.get_settings(settings.tenant_id)
        updated = await self._repo.upsert_settings(settings)
        changed: dict[str, object] = {}
        if existing is not None:
            for field_name in ("default_currency", "pf_rate", "tax_rate", "rounding"):
                new_value = getattr(settings, field_name)
                old_value = getattr(existing, field_name)
                if new_value != old_value:
                    changed[field_name] = (
                        new_value if not isinstance(new_value, Decimal) else str(new_value)
                    )
        await self._audit.log(
            action=audit_events.PAYROLL_SETTINGS_UPDATED,
            target=f"settings:{settings.tenant_id}",
            tenant_id=settings.tenant_id,
            user_id=actor_user_id,
            details=changed,
        )
        await emit_settings_updated(tenant_id=settings.tenant_id, changed_fields=changed)
        return updated

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------
    async def create_run(
        self,
        *,
        tenant_id: uuid.UUID,
        period_start: date,
        period_end: date,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollRun:
        """Rule 10: no two active runs with overlapping periods per tenant."""
        if period_end < period_start:
            raise ValueError("period_end cannot precede period_start")
        overlapping = await self._repo.find_overlapping_run(
            tenant_id, period_start=period_start, period_end=period_end
        )
        if overlapping is not None:
            raise PayrollPeriodConflictError(
                f"run {overlapping.run_code} already covers an overlapping period"
            )
        code = await self._repo.next_run_code(tenant_id)
        run = ent.PayrollRun(
            tenant_id=tenant_id,
            run_code=_next_run_code(code),
            period_start=period_start,
            period_end=period_end,
            status=PayrollRunStatus.DRAFT,
            id=uuid.uuid4(),
        )
        created = await self._repo.create_run(run)
        await self._audit.log(
            action=audit_events.PAYROLL_RUN_CREATED,
            target=f"payroll_run:{created.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        )
        if created.id is not None:
            await emit_run_created(
                run_id=created.id,
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
                tenant_id=tenant_id,
            )
        return created

    async def get_run(self, run_id: uuid.UUID, *, tenant_id: uuid.UUID) -> ent.PayrollRun | None:
        return await self._repo.get_run(run_id, tenant_id)

    async def list_runs(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ent.PayrollRun]:
        return list(
            await self._repo.list_runs(tenant_id, status=status, limit=limit, offset=offset)
        )

    async def is_computable(self, run: ent.PayrollRun) -> bool:
        """Whether a run may be (re)computed — draft/computed only.

        Pure (no IO): mirrors the guard enforced by :meth:`compute_run`. The
        batch engine calls this before enqueueing items for a run, so an
        approved/paid/void run can never be claimed for processing.
        """
        return _RUN_MACHINE.can_transition(run.status.value, PayrollRunStatus.COMPUTED.value)

    async def active_employees(
        self, run_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.Employee]:
        """Roster for a run's period — the one sanctioned cross-feature read.

        Used by the batch engine to build the per-employee item list without
        importing the HR feature.
        """
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        return await self._repo.list_active_employees(
            tenant_id,
            period_start=run.period_start,
            period_end=run.period_end,
        )

    async def compute_run(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> ComputeResult:
        """Compute entries for every active employee in the period.

        Idempotent: recomputing a draft/computed run overwrites its entries;
        approved/paid runs are immutable (Rule 8).
        """
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        try:
            _RUN_MACHINE.transition(run.status.value, PayrollRunStatus.COMPUTED.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError(
                "only draft/computed runs can be (re)computed"
            ) from None

        settings = await self._repo.get_settings(tenant_id)
        if settings is None:
            raise ValueError(f"payroll settings missing for tenant {tenant_id}")

        employees = await self._repo.list_active_employees(
            tenant_id,
            period_start=run.period_start,
            period_end=run.period_end,
        )

        # Rule 4 (docs §4.4): run the idempotent annual accrual for every
        # roster employee on every accrual-type before computing entries.
        #
        # LOCK-ORDERING CONTRACT (load-bearing, see HrRepository.lock_leave_balance):
        # each accrual takes the employee's balance-row lock. This loop MUST
        # iterate in a stable total order — `employees` is ordered by
        # employee_number (list_active_employees) and `accrual_types` by code
        # (list_accrual_leave_types) — so aggregate lock acquisition is a total
        # order across the whole roster and a concurrent single-row approver
        # (exactly one lock) can never deadlock with it. Preserve both orderings
        # if this loop or those queries ever change.
        accrual_types = await self._leave_ledger.list_accrual_leave_types(tenant_id)
        if accrual_types:
            for employee in employees:
                employee_id = _require_id(employee, "employee")
                for leave_type in accrual_types:
                    await self._leave_ledger.accrue(
                        tenant_id=tenant_id,
                        employee_id=employee_id,
                        leave_type=leave_type,
                        year=run.period_start.year,
                    )

        # Preserve manual adjustments across recompute (gap #4) and let the
        # repo drop entries for employees no longer on the roster (gap #10).
        existing_entries = {
            entry.employee_id: entry
            for entry in await self._repo.list_entries(run_id, tenant_id=tenant_id)
        }
        days_in_period = (run.period_end - run.period_start).days + 1
        entries: list[ent.PayrollEntry] = []
        skipped: list[tuple[uuid.UUID, str]] = []
        for employee in employees:
            employee_id = _require_id(employee, "employee")
            compensation = await self._repo.get_compensation(
                employee_id,
                tenant_id=tenant_id,
                effective_for=run.period_end,
            )
            if compensation is None:
                skipped.append((employee_id, "no effective compensation"))
                continue  # no effective salary for this period — no entry
            unpaid_days = await self._leave_ledger.approved_unpaid_days(
                employee_id,
                tenant_id=tenant_id,
                period_start=run.period_start,
                period_end=run.period_end,
            )
            days = PayrollCompute.pay_days(
                period_start=run.period_start,
                period_end=run.period_end,
                hire_date=employee.hire_date,
                termination_date=employee.termination_date,
                unpaid_days=unpaid_days,
            )
            if days <= 0:
                skipped.append((employee_id, "no payable days"))
                continue
            existing = existing_entries.get(employee_id)
            adjustments = existing.adjustments if existing is not None else None
            gross, deductions, net = PayrollCompute.compute_entry(
                base_salary=compensation.monthly_salary,
                pay_days=days,
                days_in_period=days_in_period,
                pf_rate=settings.pf_rate,
                tax_rate=settings.tax_rate,
                rounding=settings.rounding,
                adjustments=adjustments,
            )
            entries.append(
                ent.PayrollEntry(
                    tenant_id=tenant_id,
                    run_id=run.id if run.id is not None else run_id,
                    employee_id=employee_id,
                    base_salary=compensation.monthly_salary,
                    pay_days=days,
                    gross=gross,
                    deductions=deductions,
                    net=net,
                    adjustments=adjustments,
                    id=existing.id if existing is not None else uuid.uuid4(),
                )
            )

        await self._repo.upsert_entries(entries, tenant_id=tenant_id)
        if existing_entries:
            keep_ids = [entry.employee_id for entry in entries]
            if set(existing_entries) - set(keep_ids):
                await self._repo.delete_entries_for_run(run_id, keep_ids, tenant_id=tenant_id)
        if entries:
            total_gross, total_net = PayrollCompute.compute_totals(entries)
        else:
            currency = settings.default_currency
            total_gross = Money(Decimal("0"), currency)
            total_net = Money(Decimal("0"), currency)
        computed = await self._repo.transition_run_status(
            run_id,
            run.status.value,
            PayrollRunStatus.COMPUTED.value,
            tenant_id=tenant_id,
            computed_by=actor_user_id,
            computed_at=datetime.now(UTC),
            total_gross=total_gross,
            total_net=total_net,
            skipped_employees=[
                {"employee_id": str(employee_id), "reason": reason}
                for employee_id, reason in skipped
            ],
        )
        if computed is None:
            raise IllegalStateTransitionError(f"run is not in {run.status.value} state") from None
        await self._audit.log(
            action=audit_events.PAYROLL_RUN_COMPUTED,
            target=f"payroll_run:{run_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "entry_count": len(entries),
                "skipped_count": len(skipped),
                "skipped": [
                    {"employee_id": str(employee_id), "reason": reason}
                    for employee_id, reason in skipped
                ],
            },
        )
        if computed.id is not None:
            await emit_run_computed(
                run_id=run_id,
                period_start=run.period_start.isoformat(),
                period_end=run.period_end.isoformat(),
                total_gross=str(total_gross.amount),
                total_net=str(total_net.amount),
                tenant_id=tenant_id,
            )
        return ComputeResult(run=computed, entries=entries, skipped=skipped)

    async def compute_single(
        self,
        *,
        run_id: uuid.UUID,
        employee_id: uuid.UUID,
        tenant_id: uuid.UUID,
        persist: bool = True,
    ) -> tuple[ent.PayrollEntry | None, str | None]:
        """Compute ONE roster employee's entry — the batch engine's checkpoint seam.

        Mirrors exactly one iteration of :meth:`compute_run`'s roster loop,
        including the Rule 4 annual accrual for that employee. The accrual takes
        that employee's single balance-row lock (per item), which preserves the
        single-row lock ordering contract with a concurrent approver and avoids
        the aggregate lock-acquisition ordering a whole-roster compute needs.

        Returns ``(entry, None)`` on success — a ``None`` entry means the
        employee has no effective compensation or no payable days (nothing owed)
        — or ``(None, reason)`` when the employee could not be computed. With
        ``persist=False`` (dry-run) the entry is computed but never written.
        """
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        try:
            _RUN_MACHINE.transition(run.status.value, PayrollRunStatus.COMPUTED.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError(
                "only draft/computed runs can be (re)computed"
            ) from None

        settings = await self._repo.get_settings(tenant_id)
        if settings is None:
            raise ValueError(f"payroll settings missing for tenant {tenant_id}")

        employees = await self._repo.list_active_employees(
            tenant_id,
            period_start=run.period_start,
            period_end=run.period_end,
        )
        employee = next((e for e in employees if e.id == employee_id), None)
        if employee is None:
            return None, "employee not on the active roster for this period"
        employee_id = _require_id(employee, "employee")

        compensation = await self._repo.get_compensation(
            employee_id,
            tenant_id=tenant_id,
            effective_for=run.period_end,
        )
        if compensation is None:
            return None, "no effective compensation for this period"

        # Rule 4 (docs §4.4): idempotent annual accrual for this employee only.
        accrual_types = await self._leave_ledger.list_accrual_leave_types(tenant_id)
        for leave_type in accrual_types:
            await self._leave_ledger.accrue(
                tenant_id=tenant_id,
                employee_id=employee_id,
                leave_type=leave_type,
                year=run.period_start.year,
            )

        unpaid_days = await self._leave_ledger.approved_unpaid_days(
            employee_id,
            tenant_id=tenant_id,
            period_start=run.period_start,
            period_end=run.period_end,
        )
        days = PayrollCompute.pay_days(
            period_start=run.period_start,
            period_end=run.period_end,
            hire_date=employee.hire_date,
            termination_date=employee.termination_date,
            unpaid_days=unpaid_days,
        )
        if days <= 0:
            return None, "no payable days in this period"

        existing = await self._repo.get_entry(run_id, employee_id, tenant_id=tenant_id)
        adjustments = existing.adjustments if existing is not None else None
        days_in_period = (run.period_end - run.period_start).days + 1
        gross, deductions, net = PayrollCompute.compute_entry(
            base_salary=compensation.monthly_salary,
            pay_days=days,
            days_in_period=days_in_period,
            pf_rate=settings.pf_rate,
            tax_rate=settings.tax_rate,
            rounding=settings.rounding,
            adjustments=adjustments,
        )
        entry = ent.PayrollEntry(
            tenant_id=tenant_id,
            run_id=run.id if run.id is not None else run_id,
            employee_id=employee_id,
            base_salary=compensation.monthly_salary,
            pay_days=days,
            gross=gross,
            deductions=deductions,
            net=net,
            adjustments=adjustments,
            id=existing.id if existing is not None else uuid.uuid4(),
        )
        if persist:
            await self._repo.upsert_entries([entry], tenant_id=tenant_id)
        return entry, None

    async def finalize_compute(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
        skipped: list[dict[str, str]] | None = None,
    ) -> ent.PayrollRun:
        """Close a batch-computed run — totals, transition, audit, event.

        The batch engine persists entries item-by-item; once every item is
        terminal this finalizes the run exactly like :meth:`compute_run`'s
        tail: totals from the persisted entries, ``draft -> computed``
        (recompute ``computed -> computed``), audit row + ``payroll.run.computed``
        event.
        """
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        try:
            _RUN_MACHINE.transition(run.status.value, PayrollRunStatus.COMPUTED.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError(
                "only draft/computed runs can be (re)computed"
            ) from None

        settings = await self._repo.get_settings(tenant_id)
        entries = await self._repo.list_entries(run_id, tenant_id=tenant_id)
        if entries:
            total_gross, total_net = PayrollCompute.compute_totals(entries)
        else:
            currency = settings.default_currency if settings is not None else "USD"
            total_gross = Money(Decimal("0"), currency)
            total_net = Money(Decimal("0"), currency)

        computed = await self._repo.transition_run_status(
            run_id,
            run.status.value,
            PayrollRunStatus.COMPUTED.value,
            tenant_id=tenant_id,
            computed_by=actor_user_id,
            computed_at=datetime.now(UTC),
            total_gross=total_gross,
            total_net=total_net,
            skipped_employees=skipped or [],
        )
        if computed is None:
            raise IllegalStateTransitionError(f"run is not in {run.status.value} state") from None
        await self._audit.log(
            action=audit_events.PAYROLL_RUN_COMPUTED,
            target=f"payroll_run:{run_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"entry_count": len(entries), "skipped_count": len(skipped or [])},
        )
        if computed.id is not None:
            await emit_run_computed(
                run_id=run_id,
                period_start=run.period_start.isoformat(),
                period_end=run.period_end.isoformat(),
                total_gross=str(total_gross.amount),
                total_net=str(total_net.amount),
                tenant_id=tenant_id,
            )
        return computed

    async def approve_run(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        approved_by: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollRun:
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        try:
            _RUN_MACHINE.transition(run.status.value, PayrollRunStatus.APPROVED.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError("only computed runs can be approved") from None
        transitioned = await self._repo.transition_run_status(
            run_id,
            PayrollRunStatus.COMPUTED.value,
            PayrollRunStatus.APPROVED.value,
            tenant_id=tenant_id,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
        )
        if transitioned is None:
            raise IllegalStateTransitionError("run is not in computed state") from None
        await self._audit.log(
            action=audit_events.PAYROLL_RUN_APPROVED,
            target=f"payroll_run:{run_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
        )
        if transitioned.id is not None:
            net = transitioned.total_net
            entries = await self._repo.list_entries(run_id, tenant_id=tenant_id)
            await emit_run_approved(
                run_id=run_id,
                total_net=str(net.amount) if net is not None else "0",
                entry_count=len(entries),
                tenant_id=tenant_id,
            )
        return transitioned

    async def mark_paid(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        paid_by: uuid.UUID,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollRun:
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        try:
            _RUN_MACHINE.transition(run.status.value, PayrollRunStatus.PAID.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError("only approved runs can be marked paid") from None
        transitioned = await self._repo.transition_run_status(
            run_id,
            PayrollRunStatus.APPROVED.value,
            PayrollRunStatus.PAID.value,
            tenant_id=tenant_id,
            paid_by=paid_by,
            paid_at=datetime.now(UTC),
        )
        if transitioned is None:
            raise IllegalStateTransitionError("run is not in approved state") from None
        await self._audit.log(
            action=audit_events.PAYROLL_RUN_PAID,
            target=f"payroll_run:{run_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
        )
        if transitioned.id is not None:
            net = transitioned.total_net
            await emit_run_paid(
                run_id=run_id,
                total_net=str(net.amount) if net is not None else "0",
                paid_at=datetime.now(UTC).isoformat(),
                tenant_id=tenant_id,
            )
        return transitioned

    async def void_run(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        reason: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollRun:
        """Void from draft/computed/approved; NEVER from paid (Rule 8/§4.10)."""
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        try:
            _RUN_MACHINE.transition(run.status.value, PayrollRunStatus.VOID.value)
        except InvalidTransitionError:
            raise IllegalStateTransitionError("paid runs cannot be voided") from None
        transitioned = await self._repo.transition_run_status(
            run_id,
            run.status.value,
            PayrollRunStatus.VOID.value,
            tenant_id=tenant_id,
            void_reason=reason,
        )
        if transitioned is None:
            raise IllegalStateTransitionError("run state changed concurrently") from None
        await self._audit.log(
            action=audit_events.PAYROLL_RUN_VOIDED,
            target=f"payroll_run:{run_id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"reason": reason},
        )
        if transitioned.id is not None:
            await emit_run_voided(run_id=run_id, reason=reason, tenant_id=tenant_id)
        return transitioned

    # ------------------------------------------------------------------
    # Entries (Rule 8: immutable after approved/paid)
    # ------------------------------------------------------------------
    async def adjust_entry_by_id(
        self,
        *,
        run_id: uuid.UUID,
        entry_id: uuid.UUID,
        tenant_id: uuid.UUID,
        adjustments: dict[str, object],
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.PayrollEntry:
        """Apply a flat adjustment to an entry looked up by its row id.

        The public API addresses entries by id (``PATCH /runs/{id}/entries/
        {entry_id}``), so this resolves the entry, then behaves exactly like
        :meth:`adjust_entry`.
        """
        run = await self._repo.get_run(run_id, tenant_id)
        if run is None:
            raise ValueError(f"payroll run {run_id} not found")
        if run.status in (PayrollRunStatus.APPROVED, PayrollRunStatus.PAID):
            raise PayrollEntryImmutableError("entries are immutable once a run is approved")
        entry = await self._repo.get_entry_by_id(entry_id, tenant_id=tenant_id)
        if entry is None or entry.run_id != run_id:
            raise ValueError(f"no entry {entry_id} in run {run_id}")
        merged = {**(entry.adjustments or {}), **adjustments}
        updated = dataclasses.replace(entry, adjustments=merged)
        updated = await self._recompute_entry(updated, run=run, tenant_id=tenant_id)
        updated = await self._repo.update_entry(updated)
        await self._audit.log(
            action=audit_events.PAYROLL_ENTRY_ADJUSTED,
            target=f"payroll_entry:{updated.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={"adjustments": adjustments},
        )
        if updated.id is not None:
            await emit_entry_adjusted(
                run_id=run_id,
                employee_id=entry.employee_id,
                adjustments=adjustments,
                tenant_id=tenant_id,
            )
        return updated

    async def _recompute_entry(
        self,
        entry: ent.PayrollEntry,
        *,
        run: ent.PayrollRun,
        tenant_id: uuid.UUID,
    ) -> ent.PayrollEntry:
        """Recompute an entry's gross/deductions/net after an adjustment (gap #4).

        Uses the run's current settings; missing settings fall back to zero
        statutory rates with nearest rounding so the adjustment still applies
        (existing draft runs predate explicit settings rows).
        """
        settings = await self._repo.get_settings(tenant_id)
        pf_rate = settings.pf_rate if settings is not None else Decimal("0")
        tax_rate = settings.tax_rate if settings is not None else Decimal("0")
        rounding = settings.rounding if settings is not None else PayrollRounding.NEAREST
        days_in_period = (run.period_end - run.period_start).days + 1
        gross, deductions, net = PayrollCompute.compute_entry(
            base_salary=entry.base_salary,
            pay_days=entry.pay_days,
            days_in_period=days_in_period,
            pf_rate=pf_rate,
            tax_rate=tax_rate,
            rounding=rounding,
            adjustments=entry.adjustments,
        )
        return dataclasses.replace(entry, gross=gross, deductions=deductions, net=net)

    async def list_entries(
        self,
        run_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID | None = None,
    ) -> list[ent.PayrollEntry]:
        """Entries of one run, optionally narrowed to a single employee."""
        entries = await self._repo.list_entries(run_id, tenant_id=tenant_id)
        if employee_id is not None:
            entries = [entry for entry in entries if entry.employee_id == employee_id]
        return list(entries)

    # ------------------------------------------------------------------
    # Compensation (Rule 7: effective-date pick is repo-side; write here)
    # ------------------------------------------------------------------
    async def record_compensation(
        self,
        *,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        monthly_salary: Money,
        effective_from: date,
        actor_user_id: uuid.UUID | None = None,
    ) -> ent.Compensation:
        compensation = ent.Compensation(
            tenant_id=tenant_id,
            employee_id=employee_id,
            monthly_salary=monthly_salary,
            effective_from=effective_from,
            is_active=True,
            id=uuid.uuid4(),
        )
        created = await self._repo.create_compensation(compensation)
        await self._audit.log(
            action=audit_events.PAYROLL_COMPENSATION_RECORDED,
            target=f"compensation:{created.id}",
            tenant_id=tenant_id,
            user_id=actor_user_id,
            details={
                "employee_id": str(employee_id),
                "monthly_salary": str(monthly_salary.amount),
                "effective_from": effective_from.isoformat(),
            },
        )
        if created.id is not None:
            await emit_compensation_recorded(
                employee_id=employee_id,
                monthly_salary=str(monthly_salary.amount),
                effective_from=effective_from.isoformat(),
                tenant_id=tenant_id,
            )
        return created

    async def list_compensation(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> list[ent.Compensation]:
        """Compensation history for one employee, newest first."""
        return list(await self._repo.list_compensation(employee_id, tenant_id=tenant_id))


def _next_run_code(sequence: int) -> str:
    return f"PR-{sequence}"


__all__ = ["PayrollCompute", "PayrollService"]
