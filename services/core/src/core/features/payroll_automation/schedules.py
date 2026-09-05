"""Per-tenant recurring payroll submissions (HR-AUT-001 §5.8).

A schedule is a named 5-field cron expression on top of
``ai_payroll_schedules``; when due it submits the payroll run for the most
recent fully-elapsed calendar month (the period that is unquestionably
complete). The submission reuses the existing idempotent enqueue path, so the
settings gate and pre-flight still apply, and re-enqueueing an already-built
run is a no-op.

Fire semantics:

* no run yet for the period → ``PayrollService.create_run`` (Rule 10 overlap
  guard); then enqueue.
* an exact-period run already exists (a manual submission beat the schedule)
  → reuse it, enqueue is idempotent.
* a *wider* run overlaps the period → the fire is skipped and ``next_run_at``
  is left untouched so the sweep retries until the window opens.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from core.core.audit_events import (
    PAYROLL_AUTO_SCHEDULE_CREATED,
    PAYROLL_AUTO_SCHEDULE_DELETED,
    PAYROLL_AUTO_SCHEDULE_FIRED,
    PAYROLL_AUTO_SCHEDULE_UPDATED,
)
from core.core.audit_service import AuditService
from core.core.exceptions import PayrollPeriodConflictError
from core.features.payroll_automation.cron import parse_cron
from core.features.payroll_automation.domain import PayrollSchedule
from core.features.payroll_automation.service import (
    PayrollAutomationService,
    PayrollComputePort,
)

logger = logging.getLogger(__name__)


class PayrollScheduleRepositoryPort(Protocol):
    """Persistence contract backing :class:`PayrollSchedulerService`."""

    async def create_schedule(
        self,
        *,
        tenant_id: uuid.UUID,
        cron_expression: str,
        enabled: bool,
        name: str | None,
        next_run_at: datetime | None,
    ) -> PayrollSchedule: ...

    async def get_schedule(
        self, schedule_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> PayrollSchedule | None: ...

    async def list_schedules(self, *, tenant_id: uuid.UUID) -> list[PayrollSchedule]: ...

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        cron_expression: str,
        enabled: bool,
        name: str | None,
        next_run_at: datetime | None,
    ) -> PayrollSchedule: ...

    async def delete_schedule(self, schedule_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None: ...

    async def mark_fired(
        self,
        schedule_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        last_fired_at: datetime,
        next_run_at: datetime | None,
    ) -> None: ...

    async def list_due_schedules(self, now: datetime) -> list[PayrollSchedule]: ...


class PayrollSchedulerService:
    """Schedule CRUD + the ``run_due_schedules`` sweep consumed by the worker."""

    def __init__(
        self,
        repository: PayrollScheduleRepositoryPort,
        payroll: PayrollComputePort,
        batches: PayrollAutomationService,
        audit: AuditService | None = None,
    ) -> None:
        self._repo = repository
        self._payroll = payroll
        self._batches = batches
        self._audit = audit

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    async def create_schedule(
        self,
        *,
        tenant_id: uuid.UUID,
        cron_expression: str,
        name: str | None = None,
        enabled: bool = True,
        actor_user_id: uuid.UUID | None = None,
    ) -> PayrollSchedule:
        schedule_cron = parse_cron(cron_expression)  # raises ValueError
        schedule = await self._repo.create_schedule(
            tenant_id=tenant_id,
            cron_expression=cron_expression,
            name=name,
            enabled=enabled,
            next_run_at=schedule_cron.next_match_after(datetime.now(UTC)),
        )
        await self.insertion_log(schedule, tenant_id, actor_user_id, PAYROLL_AUTO_SCHEDULE_CREATED)
        return schedule

    async def list_schedules(self, *, tenant_id: uuid.UUID) -> list[PayrollSchedule]:
        return await self._repo.list_schedules(tenant_id=tenant_id)

    async def get_schedule(
        self, schedule_id: uuid.UUID, *, tenant_id: uuid.UUID
    ) -> PayrollSchedule | None:
        return await self._repo.get_schedule(schedule_id, tenant_id=tenant_id)

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        cron_expression: str,
        name: str | None,
        enabled: bool,
        actor_user_id: uuid.UUID | None = None,
    ) -> PayrollSchedule:
        schedule_cron = parse_cron(cron_expression)  # raises ValueError
        schedule = await self._repo.update_schedule(
            schedule_id,
            tenant_id=tenant_id,
            cron_expression=cron_expression,
            name=name,
            enabled=enabled,
            next_run_at=schedule_cron.next_match_after(datetime.now(UTC)) if enabled else None,
        )
        await self.insertion_log(schedule, tenant_id, actor_user_id, PAYROLL_AUTO_SCHEDULE_UPDATED)
        return schedule

    async def delete_schedule(self, schedule_id: uuid.UUID, *, tenant_id: uuid.UUID) -> None:
        await self._repo.delete_schedule(schedule_id, tenant_id=tenant_id)
        if self._audit is not None:
            await self._audit.log(
                action=PAYROLL_AUTO_SCHEDULE_DELETED,
                target=f"ai_payroll_schedule:{schedule_id}",
                tenant_id=tenant_id,
                user_id=None,
            )

    async def insertion_log(
        self,
        schedule: PayrollSchedule,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None,
        action: str,
    ) -> None:
        if self._audit is not None:
            await self._audit.log(
                action=action,
                target=f"ai_payroll_schedule:{schedule.id}",
                tenant_id=tenant_id,
                user_id=user_id,
                details={
                    "name": schedule.name,
                    "cron": schedule.cron_expression,
                    "enabled": schedule.enabled,
                },
            )

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------
    async def run_due_schedules(self, now: datetime | None = None) -> int:
        """Fire every enabled schedule that is due, advancing each one's next
        run. Returns the number of schedules fired. A failing schedule never
        aborts the sweep."""
        now = now or datetime.now(UTC)
        fired = 0
        for schedule in await self._repo.list_due_schedules(now):
            try:
                await self._fire_schedule(schedule, now=now)
                fired += 1
            except Exception as exc:  # a bad schedule must not block the rest
                logger.warning("payroll schedule %s failed to fire: %s", schedule.id, exc)
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.commit()
        return fired

    async def _fire_schedule(self, schedule: PayrollSchedule, *, now: datetime) -> None:
        if schedule.id is None:
            return
        tenant_id = schedule.tenant_id
        period_start, period_end = _most_recent_elapsed_month(now)
        existing = await self._payroll.find_overlapping_run(
            tenant_id, period_start=period_start, period_end=period_end
        )
        if existing is not None:
            if existing.period_start != period_start or existing.period_end != period_end:
                logger.info(
                    "payroll schedule %s skipped: wider run %s already covers %s..%s",
                    schedule.id,
                    existing.id,
                    period_start,
                    period_end,
                )
                return
            run = existing
        else:
            try:
                run = await self._payroll.create_run(
                    tenant_id=tenant_id,
                    period_start=period_start,
                    period_end=period_end,
                )
            except PayrollPeriodConflictError as exc:
                logger.info("payroll schedule %s blocked: %s", schedule.id, exc)
                return
        if run.id is None:
            return
        await self._batches.enqueue(run_id=run.id, tenant_id=tenant_id)
        schedule_cron = parse_cron(schedule.cron_expression)
        await self._repo.mark_fired(
            schedule.id,
            tenant_id=tenant_id,
            last_fired_at=now,
            next_run_at=schedule_cron.next_match_after(now),
        )
        logger.info(
            "payroll schedule %s fired; submitted run %s for %s..%s",
            schedule.id,
            run.id,
            run.period_start,
            run.period_end,
        )
        if self._audit is not None:
            await self._audit.log(
                action=PAYROLL_AUTO_SCHEDULE_FIRED,
                target=f"ai_payroll_schedule:{schedule.id}",
                tenant_id=tenant_id,
                user_id=None,
                details={
                    "run_id": str(run.id),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                },
            )

    # ------------------------------------------------------------------
    # Session plumbing
    # ------------------------------------------------------------------
    async def commit(self) -> None:
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.commit()

    async def rollback(self) -> None:
        session = getattr(self._repo, "session", None)
        if session is not None:
            await session.rollback()


def _most_recent_elapsed_month(now: datetime) -> tuple[date, date]:
    """Start/end dates of the most recent fully-elapsed calendar month."""
    first_of_this_month = now.replace(day=1)
    period_end = (first_of_this_month - timedelta(days=1)).date()
    period_start = period_end.replace(day=1)
    return period_start, period_end


__all__ = ["PayrollScheduleRepositoryPort", "PayrollSchedulerService"]
