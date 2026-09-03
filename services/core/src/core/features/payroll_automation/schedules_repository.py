"""Postgres persistence for payroll schedules (HR-AUT-001 §5.8).

``ai_payroll_schedules`` holds per-tenant recurring (cron) submissions. The
worker consumes due schedules through :meth:`list_due_schedules` and advances
each fired schedule's ``next_run_at``; CRUD backs the calendar UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from core.features.payroll_automation.domain import PayrollSchedule
from core.features.payroll_automation.models import PayrollScheduleModel

ScheduleModel = PayrollScheduleModel


def _to_schedule(row: PayrollScheduleModel) -> PayrollSchedule:
    return PayrollSchedule(
        tenant_id=row.tenant_id,
        id=row.id,
        name=row.name,
        cron_expression=row.cron_expression,
        enabled=row.enabled,
        last_fired_at=row.last_fired_at,
        next_run_at=row.next_run_at,
    )


class PostgresPayrollScheduleRepository:
    """``ai_payroll_schedules`` CRUD + due-window scans."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def create_schedule(
        self,
        *,
        tenant_id: uuid.UUID,
        cron_expression: str,
        enabled: bool,
        name: str | None,
        next_run_at: datetime | None,
    ) -> PayrollSchedule:
        row = ScheduleModel(
            tenant_id=tenant_id,
            name=name,
            cron_expression=cron_expression,
            enabled=enabled,
            next_run_at=next_run_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _to_schedule(row)

    async def get_schedule(
        self, schedule_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> PayrollSchedule | None:
        row = (
            await self._session.execute(
                sa.select(ScheduleModel).where(
                    ScheduleModel.tenant_id == tenant_id,
                    ScheduleModel.id == schedule_id,
                )
            )
        ).scalar_one_or_none()
        return _to_schedule(row) if row is not None else None

    async def list_schedules(self, *, tenant_id: uuid.UUID) -> list[PayrollSchedule]:
        rows = (
            (
                await self._session.execute(
                    sa.select(ScheduleModel)
                    .where(ScheduleModel.tenant_id == tenant_id)
                    .order_by(ScheduleModel.created_at, ScheduleModel.id)
                )
            )
            .scalars()
            .all()
        )
        return [_to_schedule(row) for row in rows]

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        cron_expression: str,
        enabled: bool,
        name: str | None,
        next_run_at: datetime | None,
    ) -> PayrollSchedule:
        stmt = (
            sa.update(ScheduleModel)
            .where(
                ScheduleModel.tenant_id == tenant_id,
                ScheduleModel.id == schedule_id,
            )
            .values(
                cron_expression=cron_expression,
                enabled=enabled,
                name=name,
                next_run_at=next_run_at,
            )
            .returning(ScheduleModel)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise ValueError(f"payroll schedule {schedule_id} not found")
        return _to_schedule(row)

    async def delete_schedule(self, schedule_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        result = await self._session.execute(
            sa.delete(ScheduleModel).where(
                ScheduleModel.tenant_id == tenant_id,
                ScheduleModel.id == schedule_id,
            )
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]  # DML returns CursorResult
            raise ValueError(f"payroll schedule {schedule_id} not found")

    async def mark_fired(
        self,
        schedule_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        last_fired_at: datetime,
        next_run_at: datetime | None,
    ) -> None:
        await self._session.execute(
            sa.update(ScheduleModel)
            .where(
                ScheduleModel.tenant_id == tenant_id,
                ScheduleModel.id == schedule_id,
            )
            .values(last_fired_at=last_fired_at, next_run_at=next_run_at)
        )

    async def list_due_schedules(self, now: datetime) -> list[PayrollSchedule]:
        """Enabled schedules whose ``next_run_at`` has arrived (cross-tenant)."""
        rows = (
            (
                await self._session.execute(
                    sa.select(ScheduleModel)
                    .where(
                        ScheduleModel.enabled.is_(True),
                        ScheduleModel.next_run_at.is_not(None),
                        ScheduleModel.next_run_at <= now,
                    )
                    .order_by(ScheduleModel.next_run_at, ScheduleModel.id)
                )
            )
            .scalars()
            .all()
        )
        return [_to_schedule(row) for row in rows]


__all__ = ["PostgresPayrollScheduleRepository"]
