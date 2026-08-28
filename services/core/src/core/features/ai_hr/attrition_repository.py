"""Attrition repository for the HR/Payroll AI slice (Commit 3).

Two responsibilities, both rooted in the ERP database:

- :meth:`build_feature_vectors` projects **anonymous numeric risk features**
  from existing ERP tables (``erp_employees``, ``erp_compensation``,
  ``erp_attendance_records``, ``erp_leave_movements``). No employee name,
  email, phone or employee number is ever selected here — only the id +
  ``department_id`` + four numbers, which is what core relays to ai-agent.
- :meth:`list_scores` / :meth:`get_score` / :meth:`upsert_scores` persist and
  read the resulting ``ai_hr_attrition_scores`` rows idempotently per
  ``(tenant_id, employee_id, model_version)``, honouring the <0.75 abstention
  (abstained employees are simply never written).

The lazy-on-read TTL (spec §6) lives in the service; this class is pure SQL.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.ai_hr.models.attrition_score import AttritionScoreModel
from core.features.hr.models.attendance_record import AttendanceRecordModel
from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel, EmploymentStatus
from core.features.hr.models.leave_movement import LeaveMovementModel
from core.features.payroll.models.compensation import CompensationModel

_ACTIVE = (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)


def _months_between(earlier: date, later: date) -> float:
    """Calendar months between two dates, fractional for the tail day."""
    return (
        float((later.year - earlier.year) * 12 + (later.month - earlier.month))
        + (later.day - earlier.day) / 30.0
    )


@dataclass(frozen=True, slots=True)
class FeatureVector:
    """One employee's anonymous risk features (never PII)."""

    employee_id: uuid.UUID
    department_id: uuid.UUID | None
    tenure_years: float
    compa_ratio: float
    promotion_gap_months: float
    activity_count: float


@dataclass(frozen=True, slots=True)
class ScoredRisk:
    """A stored attrition score, with name fields for the L2 view only.

    ``first_name``/``last_name``/``employee_number``/``department_name`` are
    populated only by :meth:`list_scores`/:meth:`get_score` for the L2
    individual shape. L1 aggregation must never serialize them — the L1
    path only reads counts/band rows.
    """

    employee_id: uuid.UUID
    department_id: uuid.UUID | None
    score: float
    risk_band: str
    confidence: float
    factors: list[dict[str, Any]] = field(default_factory=list)
    model_version: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    employee_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department_name: str | None = None
    acknowledged: bool = False
    acknowledged_by: uuid.UUID | None = None
    acknowledged_at: datetime | None = None


class AiHrAttritionRepository:
    """Read/write access to attrition features and persisted scores."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- feature projection ---------------------------------------------------

    async def build_feature_vectors(self, tenant_id: uuid.UUID) -> list[FeatureVector]:
        """Anonymous numeric features for every active employee."""
        now = date.today()
        ref_start = now - timedelta(days=365)

        latest_comp = (
            select(
                CompensationModel.employee_id,
                CompensationModel.monthly_salary,
                CompensationModel.effective_from,
            )
            .distinct(CompensationModel.employee_id)
            .where(
                CompensationModel.tenant_id == tenant_id,
                CompensationModel.is_active.is_(True),
            )
            .order_by(
                CompensationModel.employee_id,
                CompensationModel.effective_from.desc(),
            )
            .subquery()
        )

        att = (
            select(
                AttendanceRecordModel.employee_id.label("employee_id"),
                func.count().label("n"),
            )
            .where(
                AttendanceRecordModel.tenant_id == tenant_id,
                AttendanceRecordModel.work_date >= ref_start,
            )
            .group_by(AttendanceRecordModel.employee_id)
            .subquery()
        )

        leave = (
            select(
                LeaveMovementModel.employee_id.label("employee_id"),
                func.count().label("n"),
            )
            .where(
                LeaveMovementModel.tenant_id == tenant_id,
                LeaveMovementModel.occurred_at
                >= datetime.combine(ref_start, datetime.min.time(), tzinfo=UTC),
            )
            .group_by(LeaveMovementModel.employee_id)
            .subquery()
        )

        stmt = (
            select(
                EmployeeModel.id.label("employee_id"),
                EmployeeModel.department_id.label("department_id"),
                EmployeeModel.hire_date.label("hire_date"),
                latest_comp.c.monthly_salary.label("monthly_salary"),
                latest_comp.c.effective_from.label("effective_from"),
                att.c.n.label("att_n"),
                leave.c.n.label("leave_n"),
            )
            .outerjoin(latest_comp, latest_comp.c.employee_id == EmployeeModel.id)
            .outerjoin(att, att.c.employee_id == EmployeeModel.id)
            .outerjoin(leave, leave.c.employee_id == EmployeeModel.id)
            .where(
                EmployeeModel.tenant_id == tenant_id,
                EmployeeModel.employment_status.in_(_ACTIVE),
            )
        )
        rows = (await self.session.execute(stmt)).all()

        # Department salary baseline (average current salary) for compa-ratio.
        dept_salary: dict[uuid.UUID | None, list[Decimal]] = {}
        for r in rows:
            if r.monthly_salary is not None:
                dept_salary.setdefault(r.department_id, []).append(
                    cast("Decimal", r.monthly_salary)
                )
        dept_avg: dict[uuid.UUID | None, Decimal] = {
            dept: sum(salaries, Decimal(0)) / len(salaries)
            for dept, salaries in dept_salary.items()
        }

        vectors: list[FeatureVector] = []
        for r in rows:
            hire: date = r.hire_date
            months = _months_between(hire, now)
            tenure_years = round(months / 12.0, 3)
            ref_comp: date = r.effective_from if r.effective_from is not None else hire
            promotion_gap_months = round(max(0.0, _months_between(ref_comp, now)), 2)
            baseline = dept_avg.get(r.department_id)
            salary: Decimal | None = r.monthly_salary
            compa = 1.0
            if salary is not None and baseline is not None and baseline > 0:
                compa = round(float(salary / baseline), 4)
            elif salary is None:
                compa = 0.0
            activity = float(int(cast("Any", r.att_n) or 0) + int(cast("Any", r.leave_n) or 0))
            vectors.append(
                FeatureVector(
                    employee_id=r.employee_id,
                    department_id=r.department_id,
                    tenure_years=tenure_years,
                    compa_ratio=compa,
                    promotion_gap_months=promotion_gap_months,
                    activity_count=activity,
                )
            )
        return vectors

    # -- persistence ----------------------------------------------------------

    async def latest_generated_at(self, tenant_id: uuid.UUID) -> datetime | None:
        stmt = select(func.max(AttritionScoreModel.generated_at)).where(
            AttritionScoreModel.tenant_id == tenant_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert_scores(self, tenant_id: uuid.UUID, scored: Sequence[ScoredRisk]) -> None:
        """Insert-or-update one row per (employee, model_version), idempotently."""
        if not scored:
            return
        rows = [
            {
                "tenant_id": tenant_id,
                "employee_id": s.employee_id,
                "department_id": s.department_id,
                "score": s.score,
                "risk_band": s.risk_band,
                "confidence": s.confidence,
                "factors": s.factors,
                "model_version": s.model_version,
            }
            for s in scored
        ]
        stmt = insert(AttritionScoreModel).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ai_hr_attrition_scores_employee_model",
            set_={
                "department_id": stmt.excluded.department_id,
                "score": stmt.excluded.score,
                "risk_band": stmt.excluded.risk_band,
                "confidence": stmt.excluded.confidence,
                "factors": stmt.excluded.factors,
                "model_version": stmt.excluded.model_version,
                "generated_at": func.now(),
            },
        )
        await self.session.execute(stmt)

    async def _latest_run_subq(self, tenant_id: uuid.UUID) -> Any:
        return (
            select(func.max(AttritionScoreModel.generated_at).label("max_at"))
            .where(AttritionScoreModel.tenant_id == tenant_id)
            .scalar_subquery()
        )

    async def list_scores(self, tenant_id: uuid.UUID) -> list[ScoredRisk]:
        """Scores from the most recent scoring run, with names for L2 rendering."""
        dept = DepartmentModel
        stmt = (
            select(
                AttritionScoreModel.employee_id,
                AttritionScoreModel.department_id,
                AttritionScoreModel.score,
                AttritionScoreModel.risk_band,
                AttritionScoreModel.confidence,
                AttritionScoreModel.factors,
                AttritionScoreModel.model_version,
                AttritionScoreModel.generated_at,
                AttritionScoreModel.acknowledged,
                AttritionScoreModel.acknowledged_by,
                AttritionScoreModel.acknowledged_at,
                EmployeeModel.employee_number,
                EmployeeModel.first_name,
                EmployeeModel.last_name,
                dept.name.label("department_name"),
            )
            .join(
                EmployeeModel,
                and_(
                    EmployeeModel.tenant_id == AttritionScoreModel.tenant_id,
                    EmployeeModel.id == AttritionScoreModel.employee_id,
                ),
            )
            .outerjoin(
                dept,
                and_(
                    dept.tenant_id == EmployeeModel.tenant_id,
                    dept.id == AttritionScoreModel.department_id,
                ),
            )
            .where(
                AttritionScoreModel.tenant_id == tenant_id,
                AttritionScoreModel.generated_at == self._latest_run_subq(tenant_id),
            )
            .order_by(AttritionScoreModel.score.desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            ScoredRisk(
                employee_id=r.employee_id,
                department_id=r.department_id,
                score=float(cast("Any", r.score)),
                risk_band=r.risk_band,
                confidence=float(cast("Any", r.confidence)),
                factors=r.factors,
                model_version=r.model_version,
                generated_at=r.generated_at,
                employee_number=r.employee_number,
                first_name=r.first_name,
                last_name=r.last_name,
                department_name=r.department_name,
                acknowledged=r.acknowledged,
                acknowledged_by=r.acknowledged_by,
                acknowledged_at=r.acknowledged_at,
            )
            for r in rows
        ]

    async def get_score(self, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> ScoredRisk | None:
        stmt = (
            select(
                AttritionScoreModel.employee_id,
                AttritionScoreModel.department_id,
                AttritionScoreModel.score,
                AttritionScoreModel.risk_band,
                AttritionScoreModel.confidence,
                AttritionScoreModel.factors,
                AttritionScoreModel.model_version,
                AttritionScoreModel.generated_at,
                AttritionScoreModel.acknowledged,
                AttritionScoreModel.acknowledged_by,
                AttritionScoreModel.acknowledged_at,
                EmployeeModel.employee_number,
                EmployeeModel.first_name,
                EmployeeModel.last_name,
                DepartmentModel.name.label("department_name"),
            )
            .join(
                EmployeeModel,
                and_(
                    EmployeeModel.tenant_id == AttritionScoreModel.tenant_id,
                    EmployeeModel.id == AttritionScoreModel.employee_id,
                ),
            )
            .outerjoin(
                DepartmentModel,
                and_(
                    DepartmentModel.tenant_id == EmployeeModel.tenant_id,
                    DepartmentModel.id == AttritionScoreModel.department_id,
                ),
            )
            .where(
                AttritionScoreModel.tenant_id == tenant_id,
                AttritionScoreModel.employee_id == employee_id,
                AttritionScoreModel.generated_at == self._latest_run_subq(tenant_id),
            )
        )
        r = (await self.session.execute(stmt)).first()
        if r is None:
            return None
        return ScoredRisk(
            employee_id=r.employee_id,
            department_id=r.department_id,
            score=float(cast("Any", r.score)),
            risk_band=r.risk_band,
            confidence=float(cast("Any", r.confidence)),
            factors=r.factors,
            model_version=r.model_version,
            generated_at=r.generated_at,
            employee_number=r.employee_number,
            first_name=r.first_name,
            last_name=r.last_name,
            department_name=r.department_name,
            acknowledged=r.acknowledged,
            acknowledged_by=r.acknowledged_by,
            acknowledged_at=r.acknowledged_at,
        )

    async def acknowledge_score(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
    ) -> ScoredRisk | None:
        """Persist an acknowledgement on the current score row (as-of run)."""
        stmt = (
            update(AttritionScoreModel)
            .where(
                AttritionScoreModel.tenant_id == tenant_id,
                AttritionScoreModel.employee_id == employee_id,
                AttritionScoreModel.generated_at == self._latest_run_subq(tenant_id),
            )
            .values(
                acknowledged=True,
                acknowledged_by=actor_user_id,
                acknowledged_at=func.now(),
            )
        )
        await self.session.execute(stmt)
        return await self.get_score(tenant_id, employee_id)
