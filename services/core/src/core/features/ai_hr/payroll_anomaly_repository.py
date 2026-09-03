"""Payroll anomaly repository (HR-AI-001, Unit B).

Scans the tenant's LATEST non-void payroll run against the immediately
preceding run and persists findings into ``ai_payroll_anomaly_log`` by
replace-tenant scan (the leave-anomaly inbox pattern). The detection itself
lives in the PURE shared engine :mod:`skyrict_common.ai_hr_rules` — the
ai-agent eval harness grades the exact same code — and this class is the I/O
boundary (projection + persistence + read enrichment).

Rules (see the shared engine docstring): ``net_pay_delta``,
``duplicate_account``, ``ghost_employee``. Findings carry no PII in
``evidence``: accounts are masked to the last four digits. ``title`` and
``description`` have no dedicated columns on this table, so they are stored
under the ``evidence`` JSONB keys ``title`` / ``description`` and re-surfaced
as first-class fields on read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.ai_hr.models.payroll_anomaly import PayrollAnomalyModel
from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel
from core.features.payroll.models.payroll_entry import PayrollEntryModel
from core.features.payroll.models.payroll_run import PayrollRunModel, PayrollRunStatus
from skyrict_common.ai_hr_rules import (
    PayrollAnomalyFinding,
    PayrollEmployeeContext,
    PayrollEntrySignal,
    detect_payroll_anomalies,
)


@dataclass(frozen=True, slots=True)
class PayrollAnomaly:
    """One stored payroll finding, with read-side enrichment."""

    run_id: uuid.UUID
    employee_id: uuid.UUID | None
    anomaly_type: str
    severity: str
    status: str
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    anomaly_id: uuid.UUID | None = None
    run_code: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    employee_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department_name: str | None = None
    acknowledged_by: uuid.UUID | None = None
    acknowledged_at: datetime | None = None


class AiHrPayrollAnomalyRepository:
    """Read/write access to payroll anomaly signals and persisted findings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- signal projection -----------------------------------------------------

    async def build_anomaly_rows(self, tenant_id: uuid.UUID) -> list[PayrollAnomaly]:
        """Detect findings for the latest non-void run vs the preceding one."""
        runs_stmt = (
            select(
                PayrollRunModel.id,
                PayrollRunModel.run_code,
                PayrollRunModel.period_start,
                PayrollRunModel.period_end,
            )
            .where(
                PayrollRunModel.tenant_id == tenant_id,
                PayrollRunModel.status != PayrollRunStatus.VOID,
            )
            .order_by(PayrollRunModel.period_start.desc(), PayrollRunModel.created_at.desc())
        )
        runs = (await self.session.execute(runs_stmt)).all()
        if not runs:
            return []

        # The most recent run may be a DRAFT with no computed entries (the demo
        # seeds PR-2026-05 that way). Keep only runs that actually hold payroll
        # entries so the newest payable run is "latest" and its predecessor is
        # the comparison baseline.
        runs_with_rows: list = []
        for run_row in runs:
            has_rows = (
                await self.session.execute(
                    select(PayrollEntryModel.id)
                    .where(
                        PayrollEntryModel.tenant_id == tenant_id,
                        PayrollEntryModel.run_id == run_row.id,
                    )
                    .limit(1)
                )
            ).first()
            if has_rows is not None:
                runs_with_rows.append(run_row)
        if not runs_with_rows:
            return []
        latest = runs_with_rows[0]
        prior = runs_with_rows[1] if len(runs_with_rows) > 1 else None

        latest_signal = select(
            PayrollEntryModel.employee_id,
            PayrollEntryModel.net,
            PayrollEntryModel.pay_days,
        ).where(
            PayrollEntryModel.tenant_id == tenant_id,
            PayrollEntryModel.run_id == latest.id,
        )
        latest_rows = (await self.session.execute(latest_signal)).all()
        latest_entries = [
            PayrollEntrySignal(
                employee_id=e.employee_id,
                run_code=latest.run_code,
                period_start=latest.period_start,
                period_end=latest.period_end,
                base_salary=0.0,
                pay_days=int(e.pay_days or 0),
                gross=0.0,
                deductions=0.0,
                net=float(e.net),
            )
            for e in latest_rows
        ]

        prior_entries: list[PayrollEntrySignal] = []
        if prior is not None:
            prior_signal = select(
                PayrollEntryModel.employee_id,
                PayrollEntryModel.net,
                PayrollEntryModel.pay_days,
            ).where(
                PayrollEntryModel.tenant_id == tenant_id,
                PayrollEntryModel.run_id == prior.id,
            )
            for e in (await self.session.execute(prior_signal)).all():
                prior_entries.append(
                    PayrollEntrySignal(
                        employee_id=e.employee_id,
                        run_code=prior.run_code,
                        period_start=prior.period_start,
                        period_end=prior.period_end,
                        base_salary=0.0,
                        pay_days=int(e.pay_days or 0),
                        gross=0.0,
                        deductions=0.0,
                        net=float(e.net),
                    )
                )

        employees_stmt = select(
            EmployeeModel.id,
            EmployeeModel.employment_status,
            EmployeeModel.termination_date,
            EmployeeModel.bank_account,
        ).where(
            EmployeeModel.tenant_id == tenant_id,
        )
        employees = {
            r.id: PayrollEmployeeContext(
                employee_id=r.id,
                status=r.employment_status,
                termination_date=r.termination_date,
                bank_account=r.bank_account,
            )
            for r in (await self.session.execute(employees_stmt)).all()
        }

        findings = detect_payroll_anomalies(
            latest_entries=latest_entries,
            prior_entries=prior_entries,
            employees=employees,
        )
        return self._map_findings(latest, findings)

    @classmethod
    def _map_findings(
        cls,
        latest_run: Any,
        findings: list[PayrollAnomalyFinding],
    ) -> list[PayrollAnomaly]:
        now = datetime.now(UTC)
        return [
            PayrollAnomaly(
                run_id=latest_run.id,
                employee_id=f.employee_id,
                anomaly_type=f.anomaly_type,
                severity=f.severity,
                status="open",
                title=f.title,
                description=f.description,
                evidence={
                    **f.evidence,
                    "title": f.title,
                    "description": f.description,
                },
                created_at=now,
                run_code=latest_run.run_code,
            )
            for f in findings
        ]

    # -- persistence ----------------------------------------------------------

    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None:
        stmt = select(func.max(PayrollAnomalyModel.created_at)).where(
            PayrollAnomalyModel.tenant_id == tenant_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def replace_tenant_anomalies(
        self, tenant_id: uuid.UUID, rows: list[PayrollAnomaly]
    ) -> None:
        """Regenerate the tenant's payroll anomaly inbox for one scan run."""
        await self.session.execute(
            delete(PayrollAnomalyModel).where(PayrollAnomalyModel.tenant_id == tenant_id)
        )
        if not rows:
            return
        values = [
            {
                "tenant_id": tenant_id,
                "run_id": a.run_id,
                "employee_id": a.employee_id,
                "anomaly_type": a.anomaly_type,
                "severity": a.severity,
                "evidence": a.evidence,
                "status": a.status,
                "created_at": a.created_at,
            }
            for a in rows
        ]
        await self.session.execute(insert(PayrollAnomalyModel), values)

    # -- reads ----------------------------------------------------------------

    async def list_anomalies(
        self, tenant_id: uuid.UUID, employee_id: uuid.UUID | None = None
    ) -> list[PayrollAnomaly]:
        stmt = self._read_stmt(tenant_id).order_by(
            PayrollAnomalyModel.created_at.desc(),
            PayrollAnomalyModel.severity.asc(),
        )
        if employee_id is not None:
            stmt = stmt.where(PayrollAnomalyModel.employee_id == employee_id)
        rows = (await self.session.execute(stmt)).all()
        return [self._to_anomaly(r) for r in rows]

    async def get_anomaly(
        self, tenant_id: uuid.UUID, anomaly_id: uuid.UUID
    ) -> PayrollAnomaly | None:
        stmt = self._read_stmt(tenant_id).where(PayrollAnomalyModel.id == anomaly_id)
        r = (await self.session.execute(stmt)).first()
        return self._to_anomaly(r) if r is not None else None

    # -- dispositions ---------------------------------------------------------

    async def set_disposition(
        self,
        tenant_id: uuid.UUID,
        anomaly_id: uuid.UUID,
        *,
        status: str,
        actor_user_id: uuid.UUID,
    ) -> PayrollAnomaly | None:
        """Set a finding's status (open -> acknowledged|dismissed|resolved)."""
        values: dict[str, Any] = {"status": status}
        if status == "acknowledged":
            values["acknowledged_by"] = actor_user_id
            values["acknowledged_at"] = func.now()
        result = (
            await self.session.execute(
                update(PayrollAnomalyModel)
                .where(
                    PayrollAnomalyModel.tenant_id == tenant_id,
                    PayrollAnomalyModel.id == anomaly_id,
                )
                .values(**values)
                .returning(PayrollAnomalyModel.id)
            )
        ).first()
        if result is None:
            return None
        return await self.get_anomaly(tenant_id, anomaly_id)

    def _read_stmt(self, tenant_id: uuid.UUID):
        run = PayrollRunModel
        return (
            select(
                PayrollAnomalyModel.id,
                PayrollAnomalyModel.run_id,
                PayrollAnomalyModel.employee_id,
                PayrollAnomalyModel.anomaly_type,
                PayrollAnomalyModel.severity,
                PayrollAnomalyModel.evidence,
                PayrollAnomalyModel.status,
                PayrollAnomalyModel.acknowledged_by,
                PayrollAnomalyModel.acknowledged_at,
                PayrollAnomalyModel.created_at,
                run.run_code,
                run.period_start,
                run.period_end,
                EmployeeModel.employee_number,
                EmployeeModel.first_name,
                EmployeeModel.last_name,
                DepartmentModel.name.label("department_name"),
            )
            .join(
                run,
                and_(
                    run.tenant_id == PayrollAnomalyModel.tenant_id,
                    run.id == PayrollAnomalyModel.run_id,
                ),
            )
            .outerjoin(
                EmployeeModel,
                and_(
                    EmployeeModel.tenant_id == PayrollAnomalyModel.tenant_id,
                    EmployeeModel.id == PayrollAnomalyModel.employee_id,
                ),
            )
            .outerjoin(
                DepartmentModel,
                and_(
                    DepartmentModel.tenant_id == EmployeeModel.tenant_id,
                    DepartmentModel.id == EmployeeModel.department_id,
                ),
            )
            .where(PayrollAnomalyModel.tenant_id == tenant_id)
        )

    @staticmethod
    def _to_anomaly(r: Any) -> PayrollAnomaly:
        evidence = dict(r.evidence or {})
        title = str(evidence.pop("title", "Payroll anomaly"))
        description = str(evidence.pop("description", ""))
        return PayrollAnomaly(
            run_id=r.run_id,
            employee_id=r.employee_id,
            anomaly_type=r.anomaly_type,
            severity=r.severity,
            status=r.status,
            title=title,
            description=description,
            evidence=evidence,
            created_at=r.created_at,
            anomaly_id=r.id,
            run_code=r.run_code,
            period_start=r.period_start,
            period_end=r.period_end,
            employee_number=r.employee_number,
            first_name=r.first_name,
            last_name=r.last_name,
            department_name=r.department_name,
            acknowledged_by=r.acknowledged_by,
            acknowledged_at=r.acknowledged_at,
        )


__all__ = ["AiHrPayrollAnomalyRepository", "PayrollAnomaly"]
