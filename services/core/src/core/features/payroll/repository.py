"""Payroll repository — DB operations for runs, entries, settings & compensation.

Runs are the money-sensitive state machine: ``transition_run_status`` is an
atomic conditional UPDATE (``WHERE status = from_status`` RETURNING), so a
concurrent approval/void can never double-flip a run — it returns ``None`` and
the service raises ``IllegalStateTransitionError``. ``upsert_entries`` is a
bulk INSERT ... ON CONFLICT so recomputing a draft/computed run overwrites the
frozen snapshot entries in one statement (Rule 8: approved/paid runs are
immutable at the service layer — the repo never deletes).

Runs and entries have no currency column: amounts are reconstructed as
``Money`` in the tenant's settings ``default_currency``, resolved once per repo
instance (settings are seeded before payroll exists, so the cache is stable).
``next_run_code`` uses the shared tenant-scoped sequence "payroll_run" via the
injected ``next_sequence`` callable — this feature never imports ``core.db``.
``list_active_employees`` is the one sanctioned cross-feature read
(``erp_employees``), matching the ERD edge ``PayrollEntryModel.employee_id
-> erp_employees``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.core.constants import EmploymentStatus, PayrollRounding, PayrollRunStatus
from core.core.exceptions import PayrollEntryImmutableError
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.hr.models.employee import (
    EmployeeModel,
)
from core.features.hr.models.employee import (
    EmploymentStatus as EmployeeEmploymentStatus,
)
from core.features.payroll.models.compensation import CompensationModel
from core.features.payroll.models.payroll_entry import PayrollEntryModel
from core.features.payroll.models.payroll_run import (
    PayrollRounding as PayrollRoundingModel,
)
from core.features.payroll.models.payroll_run import (
    PayrollRunModel,
)
from core.features.payroll.models.payroll_run import (
    PayrollRunStatus as PayrollRunStatusModel,
)
from core.features.payroll.models.payroll_settings import PayrollSettingsModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _compensation_to_orm(compensation: ent.Compensation) -> CompensationModel:
    kwargs: dict[str, object] = {
        "tenant_id": compensation.tenant_id,
        "employee_id": compensation.employee_id,
        "monthly_salary": compensation.monthly_salary.amount,
        "currency": compensation.monthly_salary.currency,
        "effective_from": compensation.effective_from,
        "is_active": compensation.is_active,
    }
    if compensation.id is not None:
        kwargs["id"] = compensation.id
    return CompensationModel(**kwargs)


def _compensation_from_orm(model: CompensationModel) -> ent.Compensation:
    return ent.Compensation(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_id=model.employee_id,
        monthly_salary=Money(model.monthly_salary, model.currency),
        effective_from=model.effective_from,
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _run_to_orm(run: ent.PayrollRun) -> PayrollRunModel:
    kwargs: dict[str, object] = {
        "tenant_id": run.tenant_id,
        "run_code": run.run_code,
        "period_start": run.period_start,
        "period_end": run.period_end,
        "status": PayrollRunStatusModel(run.status.value),
        "total_gross": run.total_gross.amount if run.total_gross is not None else None,
        "total_net": run.total_net.amount if run.total_net is not None else None,
        "computed_by": run.computed_by,
        "approved_by": run.approved_by,
        "paid_by": run.paid_by,
        "computed_at": run.computed_at,
        "approved_at": run.approved_at,
        "paid_at": run.paid_at,
        "void_reason": run.void_reason,
        "skipped_employees": run.skipped_employees,
    }
    if run.id is not None:
        kwargs["id"] = run.id
    return PayrollRunModel(**kwargs)


def _settings_from_orm(model: PayrollSettingsModel) -> ent.PayrollSettings:
    return ent.PayrollSettings(
        id=model.id,
        tenant_id=model.tenant_id,
        default_currency=model.default_currency,
        pf_rate=model.pf_rate,
        tax_rate=model.tax_rate,
        rounding=PayrollRounding(model.rounding.value),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _employee_from_orm(model: EmployeeModel) -> ent.Employee:
    return ent.Employee(
        id=model.id,
        tenant_id=model.tenant_id,
        employee_number=model.employee_number,
        first_name=model.first_name,
        last_name=model.last_name,
        email=model.email,
        phone=model.phone,
        user_id=model.user_id,
        department_id=model.department_id,
        job_title=model.job_title,
        employment_status=EmploymentStatus(model.employment_status.value),
        hire_date=model.hire_date,
        termination_date=model.termination_date,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class PayrollRepository:
    """Concrete SQLAlchemy implementation of :class:`PayrollRepositoryPort`.

    ``next_sequence`` is the shared tenant-scoped counter provider (injected at
    the composition root as ``SequenceRepository(session).next_value``) so this
    feature never imports the ``core.db`` layer.
    """

    def __init__(
        self,
        session: AsyncSession,
        next_sequence: Callable[[uuid.UUID, str], Awaitable[int]],
    ) -> None:
        self.session = session
        self._next_sequence = next_sequence
        self._currency_cache: dict[uuid.UUID, str] = {}

    async def _currency_for(self, tenant_id: uuid.UUID) -> str:
        """Resolve the tenant's default currency once, then memoize."""
        cached = self._currency_cache.get(tenant_id)
        if cached is not None:
            return cached
        settings = await self.get_settings(tenant_id)
        currency = settings.default_currency if settings is not None else "USD"
        self._currency_cache[tenant_id] = currency
        return currency

    def _run_from_orm(self, model: PayrollRunModel, currency: str) -> ent.PayrollRun:
        return ent.PayrollRun(
            id=model.id,
            tenant_id=model.tenant_id,
            run_code=model.run_code,
            period_start=model.period_start,
            period_end=model.period_end,
            status=PayrollRunStatus(model.status.value),
            total_gross=Money(model.total_gross, currency)
            if model.total_gross is not None
            else None,
            total_net=Money(model.total_net, currency) if model.total_net is not None else None,
            computed_by=model.computed_by,
            approved_by=model.approved_by,
            paid_by=model.paid_by,
            computed_at=model.computed_at,
            approved_at=model.approved_at,
            paid_at=model.paid_at,
            void_reason=model.void_reason,
            created_at=model.created_at,
            updated_at=model.updated_at,
            skipped_employees=model.skipped_employees,
        )

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    async def get_settings(self, tenant_id: uuid.UUID) -> ent.PayrollSettings | None:
        stmt = select(PayrollSettingsModel).where(PayrollSettingsModel.tenant_id == tenant_id)
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _settings_from_orm(model) if model is not None else None

    async def upsert_settings(self, settings: ent.PayrollSettings) -> ent.PayrollSettings:
        stmt = (
            pg_insert(PayrollSettingsModel)
            .values(
                tenant_id=settings.tenant_id,
                id=settings.id if settings.id is not None else uuid.uuid4(),
                default_currency=settings.default_currency,
                pf_rate=settings.pf_rate,
                tax_rate=settings.tax_rate,
                rounding=PayrollRoundingModel(settings.rounding.value),
            )
            .on_conflict_do_update(
                index_elements=[PayrollSettingsModel.tenant_id],
                set_={
                    "default_currency": settings.default_currency,
                    "pf_rate": settings.pf_rate,
                    "tax_rate": settings.tax_rate,
                    "rounding": PayrollRoundingModel(settings.rounding.value),
                    "updated_at": func.now(),
                },
            )
            .returning(PayrollSettingsModel)
        )
        model = (await self.session.execute(stmt)).scalar_one()
        self._currency_cache[settings.tenant_id] = settings.default_currency
        return _settings_from_orm(model)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    async def create_run(self, run: ent.PayrollRun) -> ent.PayrollRun:
        model = _run_to_orm(run)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        currency = await self._currency_for(run.tenant_id)
        return self._run_from_orm(model, currency)

    async def get_run(self, run_id: uuid.UUID, tenant_id: uuid.UUID) -> ent.PayrollRun | None:
        stmt = select(PayrollRunModel).where(
            PayrollRunModel.tenant_id == tenant_id,
            PayrollRunModel.id == run_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        currency = await self._currency_for(tenant_id)
        return self._run_from_orm(model, currency)

    async def update_run(self, run: ent.PayrollRun) -> ent.PayrollRun:
        if run.id is None:
            raise ValueError("payroll run is missing an id")
        stmt = (
            update(PayrollRunModel)
            .where(
                PayrollRunModel.tenant_id == run.tenant_id,
                PayrollRunModel.id == run.id,
            )
            .values(
                run_code=run.run_code,
                period_start=run.period_start,
                period_end=run.period_end,
                status=PayrollRunStatusModel(run.status.value),
                total_gross=run.total_gross.amount if run.total_gross is not None else None,
                total_net=run.total_net.amount if run.total_net is not None else None,
                computed_by=run.computed_by,
                approved_by=run.approved_by,
                paid_by=run.paid_by,
                computed_at=run.computed_at,
                approved_at=run.approved_at,
                paid_at=run.paid_at,
                void_reason=run.void_reason,
                skipped_employees=run.skipped_employees,
                updated_at=func.now(),
            )
            .returning(PayrollRunModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise ValueError(f"payroll run {run.id} not found")
        currency = await self._currency_for(run.tenant_id)
        return self._run_from_orm(model, currency)

    async def list_runs(
        self,
        tenant_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ent.PayrollRun]:
        stmt = select(PayrollRunModel).where(PayrollRunModel.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(PayrollRunModel.status == status)
        stmt = stmt.order_by(PayrollRunModel.period_start.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        currency = await self._currency_for(tenant_id)
        return [self._run_from_orm(model, currency) for model in result.scalars().all()]

    async def find_overlapping_run(
        self,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
        exclude_run_id: uuid.UUID | None = None,
    ) -> ent.PayrollRun | None:
        """First non-void run whose period overlaps ``[period_start, period_end]``.

        Mirrors the partial unique index ``uq_erp_payroll_runs_period_active``
        (Rule 10), read side of the concurrency guard: the index rejects the
        racing INSERT, this probe fails the fast path with a clean error.
        """
        stmt = select(PayrollRunModel).where(
            PayrollRunModel.tenant_id == tenant_id,
            PayrollRunModel.status != PayrollRunStatusModel.VOID,
            PayrollRunModel.period_start <= period_end,
            PayrollRunModel.period_end >= period_start,
        )
        if exclude_run_id is not None:
            stmt = stmt.where(PayrollRunModel.id != exclude_run_id)
        stmt = stmt.order_by(PayrollRunModel.period_start.asc()).limit(1)
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        currency = await self._currency_for(tenant_id)
        return self._run_from_orm(model, currency)

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
    ) -> ent.PayrollRun | None:
        """Atomic conditional transition (CAS) — ``None`` if not in ``from_status``."""
        values: dict[str, object] = {
            "status": PayrollRunStatusModel(to_status),
            "updated_at": func.now(),
        }
        if computed_by is not None:
            values["computed_by"] = computed_by
        if approved_by is not None:
            values["approved_by"] = approved_by
        if paid_by is not None:
            values["paid_by"] = paid_by
        if computed_at is not None:
            values["computed_at"] = computed_at
        if approved_at is not None:
            values["approved_at"] = approved_at
        if paid_at is not None:
            values["paid_at"] = paid_at
        if void_reason is not None:
            values["void_reason"] = void_reason
        if total_gross is not None:
            values["total_gross"] = total_gross.amount
        if total_net is not None:
            values["total_net"] = total_net.amount
        if skipped_employees is not None:
            values["skipped_employees"] = skipped_employees
        stmt = (
            update(PayrollRunModel)
            .where(
                PayrollRunModel.tenant_id == tenant_id,
                PayrollRunModel.id == run_id,
                PayrollRunModel.status == PayrollRunStatusModel(from_status),
            )
            .values(**values)
            .returning(PayrollRunModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        currency = await self._currency_for(tenant_id)
        return self._run_from_orm(model, currency)

    async def next_run_code(self, tenant_id: uuid.UUID) -> int:
        return await self._next_sequence(tenant_id, "payroll_run")

    # ------------------------------------------------------------------
    # Entries (Rule 8: immutable after approved — the repo only upserts)
    # ------------------------------------------------------------------

    async def upsert_entries(
        self, entries: Sequence[ent.PayrollEntry], *, tenant_id: uuid.UUID
    ) -> None:
        """Bulk upsert the run snapshot — one statement, atomic with the run.

        Recompute overwrites every ``(tenant_id, run_id, employee_id)`` row so
        the snapshot always reflects the latest computation; on-conflict keeps
        the row identity and only replaces amounts/adjustments.
        """
        if not entries:
            return
        values = [
            {
                "tenant_id": entry.tenant_id,
                "id": entry.id if entry.id is not None else uuid.uuid4(),
                "run_id": entry.run_id,
                "employee_id": entry.employee_id,
                "base_salary": entry.base_salary.amount,
                "pay_days": entry.pay_days,
                "gross": entry.gross.amount,
                "deductions": entry.deductions.amount,
                "net": entry.net.amount,
                "adjustments": entry.adjustments,
            }
            for entry in entries
        ]
        stmt = pg_insert(PayrollEntryModel).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                PayrollEntryModel.tenant_id,
                PayrollEntryModel.run_id,
                PayrollEntryModel.employee_id,
            ],
            set_={
                "base_salary": stmt.excluded.base_salary,
                "pay_days": stmt.excluded.pay_days,
                "gross": stmt.excluded.gross,
                "deductions": stmt.excluded.deductions,
                "net": stmt.excluded.net,
                "adjustments": stmt.excluded.adjustments,
            },
        )
        await self.session.execute(stmt)

    async def list_entries(
        self, run_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.PayrollEntry]:
        stmt = select(PayrollEntryModel).where(
            PayrollEntryModel.tenant_id == tenant_id,
            PayrollEntryModel.run_id == run_id,
        )
        stmt = stmt.order_by(PayrollEntryModel.employee_id.asc())
        result = await self.session.execute(stmt)
        currency = await self._currency_for(tenant_id)
        return [self._entry_from_orm(model, currency) for model in result.scalars().all()]

    async def get_entry(
        self, run_id: uuid.UUID, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollEntry | None:
        stmt = select(PayrollEntryModel).where(
            PayrollEntryModel.tenant_id == tenant_id,
            PayrollEntryModel.run_id == run_id,
            PayrollEntryModel.employee_id == employee_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        currency = await self._currency_for(tenant_id)
        return self._entry_from_orm(model, currency)

    async def get_entry_by_id(
        self, entry_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> ent.PayrollEntry | None:
        """Fetch one payroll entry by its row id (API PATCH path)."""
        stmt = select(PayrollEntryModel).where(
            PayrollEntryModel.tenant_id == tenant_id,
            PayrollEntryModel.id == entry_id,
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        currency = await self._currency_for(tenant_id)
        return self._entry_from_orm(model, currency)

    async def update_entry(self, entry: ent.PayrollEntry) -> ent.PayrollEntry:
        if entry.id is None:
            raise ValueError("payroll entry is missing an id")
        # Rule 8 defense-in-depth (gap #9): never mutate an entry whose run is
        # already approved/paid, even if a caller bypasses the service layer.
        # Atomic guarded UPDATE: the immutability predicate lives in the WHERE
        # clause itself — an approved/paid/void run's entries never match the
        # subquery, so a run flipping status between a prior SELECT and this
        # statement (TOCTOU) can still never be edited. Zero rows matched means
        # the entry is missing OR its run is no longer mutable.
        stmt = (
            update(PayrollEntryModel)
            .where(
                PayrollEntryModel.tenant_id == entry.tenant_id,
                PayrollEntryModel.id == entry.id,
                PayrollEntryModel.run_id.in_(
                    select(PayrollRunModel.id).where(
                        PayrollRunModel.tenant_id == entry.tenant_id,
                        PayrollRunModel.status.in_(
                            (
                                PayrollRunStatusModel.DRAFT,
                                PayrollRunStatusModel.COMPUTED,
                            )
                        ),
                    )
                ),
            )
            .values(
                base_salary=entry.base_salary.amount,
                pay_days=entry.pay_days,
                gross=entry.gross.amount,
                deductions=entry.deductions.amount,
                net=entry.net.amount,
                adjustments=entry.adjustments,
            )
            .returning(PayrollEntryModel)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        if model is None:
            raise PayrollEntryImmutableError("entries are immutable once a run is approved")
        currency = await self._currency_for(entry.tenant_id)
        return self._entry_from_orm(model, currency)

    def _entry_from_orm(self, model: PayrollEntryModel, currency: str) -> ent.PayrollEntry:
        return ent.PayrollEntry(
            id=model.id,
            tenant_id=model.tenant_id,
            run_id=model.run_id,
            employee_id=model.employee_id,
            base_salary=Money(model.base_salary, currency),
            pay_days=model.pay_days,
            gross=Money(model.gross, currency),
            deductions=Money(model.deductions, currency),
            net=Money(model.net, currency),
            adjustments=model.adjustments,
            created_at=model.created_at,
        )

    async def delete_entries_for_run(
        self,
        run_id: uuid.UUID,
        employee_ids: Sequence[uuid.UUID],
        *,
        tenant_id: uuid.UUID,
    ) -> int:
        """Delete run entries whose employee is no longer on the roster (gap #10).

        Only ever removes employees that were NOT recomputed, so a recompute
        that shrinks the roster does not leave ghost rows in the snapshot.
        Returns the number of deleted rows.
        """
        stmt = delete(PayrollEntryModel).where(
            PayrollEntryModel.tenant_id == tenant_id,
            PayrollEntryModel.run_id == run_id,
            PayrollEntryModel.employee_id.not_in(employee_ids),
        )
        result = await self.session.execute(stmt)
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # Compensation (effective-date pick per Rule 7)
    # ------------------------------------------------------------------

    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation:
        model = _compensation_to_orm(compensation)
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _compensation_from_orm(model)

    async def get_compensation(
        self,
        employee_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        effective_for: date,
    ) -> ent.Compensation | None:
        """The active compensation effective at or before ``effective_for``.

        Rule 7: latest ``effective_from`` row with ``is_active`` among those
        effective no later than the payroll period end.
        """
        stmt = (
            select(CompensationModel)
            .where(
                CompensationModel.tenant_id == tenant_id,
                CompensationModel.employee_id == employee_id,
                CompensationModel.is_active.is_(True),
                CompensationModel.effective_from <= effective_for,
            )
            .order_by(CompensationModel.effective_from.desc())
            .limit(1)
        )
        model = (await self.session.execute(stmt)).scalar_one_or_none()
        return _compensation_from_orm(model) if model is not None else None

    async def list_compensation(
        self, employee_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> Sequence[ent.Compensation]:
        """Full compensation history for one employee, newest first."""
        stmt = (
            select(CompensationModel)
            .where(
                CompensationModel.tenant_id == tenant_id,
                CompensationModel.employee_id == employee_id,
            )
            .order_by(CompensationModel.effective_from.desc())
        )
        result = await self.session.execute(stmt)
        return [_compensation_from_orm(model) for model in result.scalars().all()]

    # ------------------------------------------------------------------
    # Roster (read-only, one-way erp_employees read per the ERD)
    # ------------------------------------------------------------------

    async def list_active_employees(
        self,
        tenant_id: uuid.UUID,
        *,
        period_start: date,
        period_end: date,
    ) -> Sequence[ent.Employee]:
        """Payroll roster for a period (gap #5), ordered by employee_number.

        Docs §4.9: the roster is everyone hired by the period end who is NOT
        terminated, plus employees who were terminated during the period (they
        earn through their termination date, Rule 9 prorates ``pay_days``).
        ``on_leave`` employees stay on the roster and still earn base pay.
        """
        stmt = select(EmployeeModel).where(
            EmployeeModel.tenant_id == tenant_id,
            EmployeeModel.hire_date <= period_end,
            (
                (EmployeeModel.employment_status != EmployeeEmploymentStatus.TERMINATED)
                | (
                    (EmployeeModel.employment_status == EmployeeEmploymentStatus.TERMINATED)
                    & (EmployeeModel.termination_date >= period_start)
                )
            ),
        )
        stmt = stmt.order_by(EmployeeModel.employee_number.asc())
        result = await self.session.execute(stmt)
        return [_employee_from_orm(model) for model in result.scalars().all()]
