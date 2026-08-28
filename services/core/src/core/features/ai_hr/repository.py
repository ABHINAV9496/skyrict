"""L1 aggregate repository for the HR/Payroll AI slice.

All methods here are SQL ``GROUP BY``/aggregate over existing ERP tables
(``erp_employees``, ``erp_departments``). **No employee row is ever selected
and serialized** — the guarantee behind the L1 data-scope level (spec §5). The
only identifiers that may appear are department ids; employee ids, names, email,
phones and employee numbers are never projected.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from core.features.hr.models.department import DepartmentModel
from core.features.hr.models.employee import EmployeeModel, EmploymentStatus


@dataclass(frozen=True, slots=True)
class HeadcountPoint:
    """One month's hires among currently-active employees."""

    year: int
    month: int
    hires: int


@dataclass(frozen=True, slots=True)
class DepartmentCount:
    """Headcount per department among active employees."""

    department_id: uuid.UUID | None
    department_name: str
    count: int


@dataclass(frozen=True, slots=True)
class TenureBand:
    """Headcount in one tenure band."""

    band: str
    count: int


@dataclass(frozen=True, slots=True)
class Overview:
    """The L1 headcount/tenure overview — aggregate rows only."""

    total_headcount: int
    trend: list[HeadcountPoint] = field(default_factory=list)
    departments: list[DepartmentCount] = field(default_factory=list)
    tenure_bands: list[TenureBand] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    narrative: str = ""


@dataclass(frozen=True, slots=True)
class TenureSummary:
    """The L1 tenure-band summary with narrative."""

    total_headcount: int
    bands: list[TenureBand] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    narrative: str = ""


class AiHrRepository:
    """Read projection for L1 HR aggregates over existing ERP tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def total_headcount(self, tenant_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(EmployeeModel)
            .where(
                EmployeeModel.tenant_id == tenant_id,
                EmployeeModel.employment_status.in_(
                    (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)
                ),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def headcount_trend(self, tenant_id: uuid.UUID, months: int = 12) -> list[HeadcountPoint]:
        """Hires per calendar month (last ``months`` months) among active staff."""
        month = func.date_trunc("month", EmployeeModel.hire_date)
        stmt = (
            select(
                func.extract("year", month).label("year"),
                func.extract("month", month).label("month"),
                func.count().label("hires"),
            )
            .where(
                EmployeeModel.tenant_id == tenant_id,
                EmployeeModel.employment_status.in_(
                    (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)
                ),
            )
            .group_by(month)
            .order_by(month.desc())
            .limit(months)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            HeadcountPoint(year=int(r.year), month=int(r.month), hires=int(r.hires)) for r in rows
        ]

    async def department_distribution(self, tenant_id: uuid.UUID) -> list[DepartmentCount]:
        """Active headcount per department (left join keeps null-dept hires)."""
        dept = aliased(DepartmentModel)
        stmt = (
            select(
                EmployeeModel.department_id.label("department_id"),
                func.coalesce(dept.name, "Unassigned").label("department_name"),
                func.count().label("count"),
            )
            .outerjoin(
                dept,
                (dept.tenant_id == EmployeeModel.tenant_id)
                & (dept.id == EmployeeModel.department_id),
            )
            .where(
                EmployeeModel.tenant_id == tenant_id,
                EmployeeModel.employment_status.in_(
                    (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)
                ),
            )
            .group_by(EmployeeModel.department_id, "department_name")
            .order_by(func.count().desc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            DepartmentCount(
                department_id=r.department_id,
                department_name=r.department_name,
                count=int(cast("Any", r.count)),
            )
            for r in rows
        ]

    async def tenure_bands(self, tenant_id: uuid.UUID) -> list[TenureBand]:
        """Active headcount bucketed into tenure bands (SQL-side only)."""
        years = func.extract("year", func.age(func.current_date(), EmployeeModel.hire_date))
        band = case(
            (years < 1, "<1"),
            (years < 3, "1-3"),
            (years < 5, "3-5"),
            (years < 10, "5-10"),
            else_="10+",
        )
        stmt = (
            select(band.label("band"), func.count().label("count"))
            .where(
                EmployeeModel.tenant_id == tenant_id,
                EmployeeModel.employment_status.in_(
                    (EmploymentStatus.ACTIVE, EmploymentStatus.ON_LEAVE)
                ),
            )
            .group_by(band)
            .order_by(band)
        )
        rows = (await self.session.execute(stmt)).all()
        return [TenureBand(band=r.band, count=int(cast("Any", r.count))) for r in rows]
