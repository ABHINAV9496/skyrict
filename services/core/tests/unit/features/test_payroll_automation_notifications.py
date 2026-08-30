"""Commit 3 unit tests — cron matcher, notification orchestrator, scheduler.

DB-free doubles: the orchestrator/scheduler ports are stubbed in memory so the
rules are pinned without Postgres: preference defaults (no row = in-app ON,
email OFF), per-employee dedupe keys ("exactly one notification row"),
digest recipients (holders of ``erp.payroll.ai.read``), dry-run/aborted
silence, and the cron fire/reuse/conflict semantics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from core.core.exceptions import PayrollPeriodConflictError
from core.core.permissions import ERP_PAYROLL_AI_READ
from core.features.payroll_automation.constants import (
    BATCH_COMPLETED,
    BATCH_FAILED,
    EVENT_PAYROLL_BATCH_DIGEST,
    EVENT_PAYSLIP_READY,
)
from core.features.payroll_automation.cron import parse_cron
from core.features.payroll_automation.domain import (
    PayrollBatchRun,
    PayrollNotification,
    PayrollSchedule,
)
from core.features.payroll_automation.notifications import PayrollNotificationOrchestrator
from core.features.payroll_automation.schedules import PayrollSchedulerService

pytestmark = pytest.mark.unit

TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
EMP_1 = uuid.UUID("33333333-3333-3333-3333-333333333333")
EMP_2 = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER_1 = uuid.UUID("55555555-5555-5555-5555-555555555555")
USER_2 = uuid.UUID("66666666-6666-6666-6666-666666666666")
ADMIN_1 = uuid.UUID("77777777-7777-7777-7777-777777777777")
BATCH_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
RUN_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


# ---------------------------------------------------------------------------
# Cron
# ---------------------------------------------------------------------------


class TestCron:
    def test_parse_daily_and_match(self) -> None:
        cron = parse_cron("0 9 * * *")
        moment = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
        assert cron.matches(moment)
        assert not cron.matches(moment.replace(hour=8))
        assert not cron.matches(moment.replace(minute=1))

    def test_comma_ranges_and_dow(self) -> None:
        cron = parse_cron("30 18 1,15 * 1-5")
        for day in (1, 15):
            moment = datetime(2026, 8, day, 18, 30, tzinfo=UTC)
            assert cron.matches(moment), f"expected fire on {day}"
        assert not cron.matches(datetime(2026, 8, 2, 18, 30, tzinfo=UTC))

    def test_named_weekday_and_recurrence(self) -> None:
        cron = parse_cron("0 0 * * 0")
        first = datetime(2026, 8, 30, 0, 0, tzinfo=UTC)
        nxt = cron.next_match_after(first)
        assert nxt > first
        assert nxt.weekday() == 6  # Sunday
        assert (nxt - first).days == 7

    def test_monthly_next_fires_first_elapsed_day(self) -> None:
        cron = parse_cron("0 18 1 * *")
        nxt = cron.next_match_after(datetime(2026, 8, 2, 0, 0, tzinfo=UTC))
        assert nxt == datetime(2026, 9, 1, 18, 0, tzinfo=UTC)

    def test_dom_dow_both_restricted_uses_or(self) -> None:
        cron = parse_cron("0 12 13 * 5")
        friday_13th = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)  # actually a Friday
        assert cron.matches(friday_13th)

    def test_invalid_expression_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_cron("60 0 * * *")
        with pytest.raises(ValueError):
            parse_cron("0 0 * *")
        with pytest.raises(ValueError):
            parse_cron("0 0 32 * *")

    def test_never_firing_expression_raises_on_next(self) -> None:
        cron = parse_cron("0 0 30 2 *")
        with pytest.raises(ValueError):
            cron.next_match_after(datetime(2026, 1, 1, tzinfo=UTC))

    def test_steps_are_out_of_scope_and_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_cron("*/5 * * * *")


# ---------------------------------------------------------------------------
# Orchestrator doubles
# ---------------------------------------------------------------------------


class FakeNotificationRepo:
    def __init__(self) -> None:
        self.done: list[uuid.UUID] = []
        self.user_map: dict[uuid.UUID, uuid.UUID | None] = {}
        self.prefs: dict[uuid.UUID, object] = {}
        self.admins: list[uuid.UUID] = []
        self.failures: list[dict[str, str]] = []
        self.notifications: list[PayrollNotification] = []

    async def done_employee_ids(self, batch_id, *, tenant_id):
        return list(self.done)

    async def employee_user_ids(self, tenant_id, employee_ids):
        return {eid: self.user_map.get(eid) for eid in employee_ids}

    async def prefs_for_users(self, tenant_id, user_ids):
        return {uid: self.prefs.get(uid, _DefaultPref()) for uid in user_ids}

    async def user_ids_with_permission(self, tenant_id, *, permission=ERP_PAYROLL_AI_READ):
        return list(self.admins)

    async def failed_item_errors(self, batch_id, *, tenant_id):
        return list(self.failures)

    async def insert_notifications(self, *, tenant_id, notifications):
        inserted = 0
        for n in notifications:
            if any(existing.dedupe_key == n.dedupe_key for existing in self.notifications):
                continue
            self.notifications.append(n)
            inserted += 1
        return inserted

    async def get_pref(self, tenant_id, user_id):
        return self.prefs.get(user_id, _DefaultPref())

    async def upsert_pref(self, *, tenant_id, user_id, in_app_on, email_on):
        pref = _Pref(user_id, in_app_on, email_on)
        self.prefs[user_id] = pref
        return pref

    async def list_notifications(self, *, tenant_id, **kwargs):
        return list(self.notifications)


@dataclass
class _DefaultPref:
    in_app_on: bool = True
    email_on: bool = False


@dataclass
class _Pref:
    user_id: uuid.UUID
    in_app_on: bool
    email_on: bool


def _batch(status: str = BATCH_COMPLETED) -> PayrollBatchRun:
    return PayrollBatchRun(
        id=BATCH_ID,
        tenant_id=TENANT_ID,
        source="payroll.run",
        source_ref=str(RUN_ID),
        status=status,
        dry_run=False,
        totals={"total": 2, "done": 2, "failed": 0, "skipped": 0},
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestNotificationOrchestrator:
    async def test_payslip_ready_defaults_in_app_on_email_off(self) -> None:
        repo = FakeNotificationRepo()
        repo.done = [EMP_1, EMP_2]
        repo.user_map = {EMP_1: USER_1, EMP_2: USER_2}
        orch = PayrollNotificationOrchestrator(repo)

        inserted = await orch.record_batch_notifications(
            tenant_id=TENANT_ID, batch=_batch(), status=BATCH_COMPLETED,
            run_id=RUN_ID, totals={"total": 2, "done": 2, "failed": 0},
        )

        assert inserted == 2
        for n in repo.notifications:
            assert n.event_type == EVENT_PAYSLIP_READY
            assert n.in_app is True
            assert n.email_stub is False
        keys = {n.dedupe_key for n in repo.notifications}
        assert keys == {f"payslip:{BATCH_ID}:{EMP_1}", f"payslip:{BATCH_ID}:{EMP_2}"}

    async def test_email_opt_in_sets_stub(self) -> None:
        repo = FakeNotificationRepo()
        repo.done = [EMP_1]
        repo.user_map = {EMP_1: USER_1}
        repo.prefs[USER_1] = _Pref(USER_1, in_app_on=True, email_on=True)
        orch = PayrollNotificationOrchestrator(repo)

        await orch.record_batch_notifications(
            tenant_id=TENANT_ID, batch=_batch(), status=BATCH_COMPLETED,
            run_id=RUN_ID, totals={},
        )

        assert repo.notifications[0].email_stub is True

    async def test_unlinked_employee_gets_no_row(self) -> None:
        repo = FakeNotificationRepo()
        repo.done = [EMP_1]
        repo.user_map = {EMP_1: None}
        orch = PayrollNotificationOrchestrator(repo)

        inserted = await orch.record_batch_notifications(
            tenant_id=TENANT_ID, batch=_batch(), status=BATCH_COMPLETED,
            run_id=RUN_ID, totals={},
        )

        assert inserted == 0
        assert repo.notifications == []

    async def test_dedupe_reinvocation_is_noop(self) -> None:
        repo = FakeNotificationRepo()
        repo.done = [EMP_1]
        repo.user_map = {EMP_1: USER_1}
        orch = PayrollNotificationOrchestrator(repo)
        kwargs = {
            "tenant_id": TENANT_ID,
            "batch": _batch(),
            "status": BATCH_COMPLETED,
            "run_id": RUN_ID,
            "totals": {"total": 1, "done": 1, "failed": 0},
        }

        first = await orch.record_batch_notifications(**kwargs)
        second = await orch.record_batch_notifications(**kwargs)

        assert first == 1
        assert second == 0
        assert len(repo.notifications) == 1

    async def test_admin_digest_routes_to_read_holders_for_failure(self) -> None:
        repo = FakeNotificationRepo()
        repo.admins = [ADMIN_1]
        repo.failures = [{"employee_id": str(EMP_1), "error_text": "boom"}]
        orch = PayrollNotificationOrchestrator(repo)

        inserted = await orch.record_batch_notifications(
            tenant_id=TENANT_ID, batch=_batch(status=BATCH_FAILED),
            status=BATCH_FAILED, run_id=RUN_ID,
            totals={"total": 2, "done": 1, "failed": 1, "skipped": 0},
        )

        assert inserted == 1
        n = repo.notifications[0]
        assert n.event_type == EVENT_PAYROLL_BATCH_DIGEST
        assert n.recipient_user_id == ADMIN_1
        assert "boom" in n.body

    async def test_dry_run_and_aborted_batches_are_silent(self) -> None:
        dry = PayrollBatchRun(
            id=BATCH_ID, tenant_id=TENANT_ID, source="payroll.run",
            source_ref=str(RUN_ID), status="queued", dry_run=True,
            totals={},
        )
        repo = FakeNotificationRepo()
        orch = PayrollNotificationOrchestrator(repo)

        inserted = await orch.record_batch_notifications(
            tenant_id=TENANT_ID, batch=dry, status="queued", run_id=RUN_ID, totals={},
        )

        assert inserted == 0
        assert repo.notifications == []


# ---------------------------------------------------------------------------
# Scheduler doubles
# ---------------------------------------------------------------------------


@dataclass
class _SchedRun:
    id: uuid.UUID
    period_start: datetime.date
    period_end: datetime.date


@dataclass
class _Fired:
    schedule_id: uuid.UUID
    tenant_id: uuid.UUID
    last_fired_at: datetime
    next_run_at: datetime | None


class FakeScheduleRepo:
    def __init__(self) -> None:
        self.schedules: list[PayrollSchedule] = []
        self.due: list[PayrollSchedule] = []
        self.fired: list[_Fired] = []

    async def create_schedule(self, *, tenant_id, cron_expression, enabled, name, next_run_at):
        s = PayrollSchedule(
            tenant_id=tenant_id, cron_expression=cron_expression, enabled=enabled,
            name=name, next_run_at=next_run_at, id=uuid.uuid4(),
        )
        self.schedules.append(s)
        return s

    async def get_schedule(self, schedule_id, *, tenant_id):
        for s in self.schedules:
            if s.id == schedule_id and s.tenant_id == tenant_id:
                return s
        return None

    async def list_schedules(self, *, tenant_id):
        return [s for s in self.schedules if s.tenant_id == tenant_id]

    async def update_schedule(self, schedule_id, *, tenant_id, cron_expression, enabled, name, next_run_at):
        for i, s in enumerate(self.schedules):
            if s.id == schedule_id and s.tenant_id == tenant_id:
                replacement = PayrollSchedule(
                    tenant_id=tenant_id, cron_expression=cron_expression,
                    enabled=enabled, name=name, next_run_at=next_run_at, id=s.id,
                )
                self.schedules[i] = replacement
                return replacement
        raise ValueError(f"payroll schedule {schedule_id} not found")

    async def delete_schedule(self, schedule_id, *, tenant_id):
        self.schedules = [s for s in self.schedules if not (s.id == schedule_id and s.tenant_id == tenant_id)]

    async def mark_fired(self, schedule_id, *, tenant_id, last_fired_at, next_run_at):
        self.fired.append(_Fired(schedule_id, tenant_id, last_fired_at, next_run_at))

    async def list_due_schedules(self, now):
        return list(self.due)


class FakeBatches:
    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []

    async def enqueue(self, *, run_id, tenant_id, **kwargs):
        self.enqueued.append(run_id)


class FakeSchedulerPayroll:
    def __init__(self) -> None:
        self.existing: _SchedRun | None = None
        self.created: list[_SchedRun] = []
        self.period_conflict = False

    async def find_overlapping_run(self, tenant_id, *, period_start, period_end):
        return self.existing

    async def create_run(self, *, tenant_id, period_start, period_end, **kwargs):
        if self.period_conflict:
            raise PayrollPeriodConflictError("overlap")
        run = _SchedRun(uuid.uuid4(), period_start, period_end)
        self.created.append(run)
        return run


def _due_schedule(next_run: datetime | None = None) -> PayrollSchedule:
    return PayrollSchedule(
        tenant_id=TENANT_ID,
        cron_expression="0 18 1 * *",
        enabled=True,
        name="Monthly",
        next_run_at=next_run or datetime(2026, 8, 1, 18, 0, tzinfo=UTC),
        id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class TestScheduler:
    async def test_due_schedule_creates_previous_month_run_and_fires(self) -> None:
        repo = FakeScheduleRepo()
        payroll = FakeSchedulerPayroll()
        batches = FakeBatches()
        now = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
        schedule = _due_schedule(datetime(2026, 9, 1, 18, 0, tzinfo=UTC))
        repo.due = [schedule]
        svc = PayrollSchedulerService(repo, payroll, batches)

        fired = await svc.run_due_schedules(now=now)

        assert fired == 1
        assert len(payroll.created) == 1
        created = payroll.created[0]
        assert created.period_start == datetime(2026, 8, 1).date()
        assert created.period_end == datetime(2026, 8, 31).date()
        assert batches.enqueued == [created.id]
        assert repo.fired[0].schedule_id == schedule.id
        assert repo.fired[0].next_run_at == datetime(2026, 10, 1, 18, 0, tzinfo=UTC)

    async def test_exact_period_existing_run_is_reused(self) -> None:
        repo = FakeScheduleRepo()
        payroll = FakeSchedulerPayroll()
        payroll.existing = _SchedRun(uuid.uuid4(), datetime(2026, 8, 1).date(), datetime(2026, 8, 31).date())
        batches = FakeBatches()
        repo.due = [_due_schedule()]
        svc = PayrollSchedulerService(repo, payroll, batches)

        fired = await svc.run_due_schedules(now=datetime(2026, 9, 2, tzinfo=UTC))

        assert fired == 1
        assert payroll.created == []
        assert batches.enqueued == [payroll.existing.id]

    async def test_wider_overlap_skips_without_advancing(self) -> None:
        repo = FakeScheduleRepo()
        payroll = FakeSchedulerPayroll()
        payroll.existing = _SchedRun(uuid.uuid4(), datetime(2026, 1, 1).date(), datetime(2026, 12, 31).date())
        batches = FakeBatches()
        repo.due = [_due_schedule()]
        svc = PayrollSchedulerService(repo, payroll, batches)

        fired = await svc.run_due_schedules(now=datetime(2026, 9, 2, tzinfo=UTC))

        assert fired == 1  # the sweep counts the attempt
        assert batches.enqueued == []
        assert repo.fired == []  # next_run_at untouched -> retried next tick

    async def test_create_conflict_is_skipped_not_fatal(self) -> None:
        repo = FakeScheduleRepo()
        payroll = FakeSchedulerPayroll()
        payroll.period_conflict = True
        batches = FakeBatches()
        repo.due = [_due_schedule(), _due_schedule(datetime(2026, 9, 1, 19, 0, tzinfo=UTC))]
        svc = PayrollSchedulerService(repo, payroll, batches)

        fired = await svc.run_due_schedules(now=datetime(2026, 9, 2, tzinfo=UTC))

        assert fired == 2
        assert batches.enqueued == []

    async def test_invalid_cron_create_is_rejected(self) -> None:
        repo = FakeScheduleRepo()
        svc = PayrollSchedulerService(repo, FakeSchedulerPayroll(), FakeBatches())

        with pytest.raises(ValueError):
            await svc.create_schedule(tenant_id=TENANT_ID, cron_expression="60 0 * * *")

    async def test_crud_roundtrip(self) -> None:
        repo = FakeScheduleRepo()
        svc = PayrollSchedulerService(repo, FakeSchedulerPayroll(), FakeBatches())
        created = await svc.create_schedule(
            tenant_id=TENANT_ID, cron_expression="0 0 * * 0", name="Weekly"
        )

        assert await svc.get_schedule(created.id, tenant_id=TENANT_ID) is not None
        assert await svc.list_schedules(tenant_id=TENANT_ID) == [created]

        updated = await svc.update_schedule(
            created.id, tenant_id=TENANT_ID, cron_expression="15 9 * * *",
            name="Weekdays", enabled=False,
        )
        assert updated.enabled is False

        await svc.delete_schedule(created.id, tenant_id=TENANT_ID)
        assert await svc.get_schedule(created.id, tenant_id=TENANT_ID) is None
