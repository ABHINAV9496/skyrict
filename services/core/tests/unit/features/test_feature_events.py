"""Feature event tests — after-commit buffer + new emitters (docs §2.5).

Covers the after-commit buffer added for gap #12 and the emitters added for
gaps #7/#8. Unit-level: the process-wide stub producer is swapped for a
recording double; emit functions are exercised directly and through the
services. Buffer lifecycle (start/flush/clear) is driven by ``get_db`` at the
integration layer, so the buffer mechanics are tested here in isolation.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from core.core.audit_service import AuditService
from core.core.constants import EmploymentStatus, LeaveRequestStatus
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.events.producers import (
    apublish,
    buffered_events,
    clear_event_buffer,
    flush_events,
    start_event_buffer,
)
from core.events.producers.hr_events import emit_leave_cancelled
from core.events.producers.payroll_events import emit_compensation_recorded
from core.features.hr.service import DepartmentService, LeaveService
from core.features.payroll.service import PayrollService

if TYPE_CHECKING:
    from skyrict_events.base import BaseEvent

pytestmark = pytest.mark.unit

TENANT = uuid.uuid4()


class RecordingProducer:
    """Swap-in for the process-wide stub — records every published event."""

    def __init__(self) -> None:
        self.published: list[tuple[str, BaseEvent, str | None]] = []

    def publish(self, topic: str, event: BaseEvent, *, key: str | None = None) -> None:
        self.published.append((topic, event, key))

    async def apublish(self, topic: str, event: BaseEvent, *, key: str | None = None) -> None:
        self.publish(topic, event, key=key)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.added: list[ent.AuditLogEntry] = []

    async def add(self, entry: ent.AuditLogEntry) -> ent.AuditLogEntry:
        self.added.append(entry)
        return entry

    async def list(self, tenant_id: uuid.UUID, *, action: str | None = None, limit: int = 100):
        return self.added

    async def get(self, tenant_id: uuid.UUID, entry_id: uuid.UUID) -> ent.AuditLogEntry | None:
        return None


class FakeHrRepository:
    def __init__(self) -> None:
        self.departments: dict[uuid.UUID, ent.Department] = {}
        self.employees: dict[uuid.UUID, ent.Employee] = {}
        self.requests: dict[uuid.UUID, ent.LeaveRequest] = {}
        self.leave_types: dict[str, ent.LeaveType] = {}

    async def create_department(self, department: ent.Department) -> ent.Department:
        self.departments[department.id] = department
        return department

    async def get_department(self, department_id: uuid.UUID, tenant_id: uuid.UUID):
        return self.departments.get(department_id)

    async def update_department(self, department: ent.Department) -> ent.Department:
        self.departments[department.id] = department
        return department

    async def create_employee(self, employee: ent.Employee) -> ent.Employee:
        self.employees[employee.id] = employee
        return employee

    async def get_employee(self, employee_id: uuid.UUID, tenant_id: uuid.UUID):
        return self.employees.get(employee_id)

    async def get_leave_type(self, leave_type: str, tenant_id: uuid.UUID):
        return self.leave_types.get(leave_type)

    async def create_leave_request(self, request: ent.LeaveRequest) -> ent.LeaveRequest:
        self.requests[request.id] = request
        return request

    async def get_leave_request(self, request_id: uuid.UUID, tenant_id: uuid.UUID):
        return self.requests.get(request_id)

    async def transition_leave_status(
        self,
        request_id: uuid.UUID,
        from_status: str,
        to_status: str,
        *,
        tenant_id: uuid.UUID,
        approved_by=None,
        approved_at=None,
    ):
        current = self.requests.get(request_id)
        if current is None or current.status.value != from_status:
            return None
        updated = ent.LeaveRequest(
            tenant_id=current.tenant_id,
            employee_id=current.employee_id,
            leave_type=current.leave_type,
            start_date=current.start_date,
            end_date=current.end_date,
            days=current.days,
            status=LeaveRequestStatus(to_status),
            reason=current.reason,
            id=current.id,
        )
        self.requests[request_id] = updated
        return updated

    async def recompute_balance(self, employee_id, leave_type, *, tenant_id) -> int:
        return 0

    async def lock_leave_balance(self, employee_id, leave_type, *, tenant_id) -> None:
        """No-op in the in-memory double: nothing to serialize without a DB."""

    async def list_leave_movements(self, tenant_id, employee_id, leave_type=None):
        return []


class FakePayrollRepository:
    def __init__(self) -> None:
        self.compensation: list[ent.Compensation] = []

    async def create_compensation(self, compensation: ent.Compensation) -> ent.Compensation:
        self.compensation.append(compensation)
        return compensation


class TestEventBuffer:
    async def test_buffered_events_are_not_published_until_flush(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        producer = RecordingProducer()
        monkeypatch.setattr("core.events.producers._event_producer", producer)
        start_event_buffer()
        try:
            await emit_leave_cancelled(
                request_id=uuid.uuid4(),
                employee_id=uuid.uuid4(),
                leave_type="annual",
                days=2,
                tenant_id=TENANT,
            )
            assert producer.published == []
            assert len(buffered_events()) == 1
            await flush_events()
            assert len(producer.published) == 1
            assert producer.published[0][0] == "hr.leave.cancelled"
            assert buffered_events() == []
        finally:
            clear_event_buffer()

    async def test_clear_discards_buffered_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        producer = RecordingProducer()
        monkeypatch.setattr("core.events.producers._event_producer", producer)
        start_event_buffer()
        try:
            await apublish("test.topic", _envelope("test.topic"))
            clear_event_buffer()
            await flush_events()
            assert producer.published == []
        finally:
            clear_event_buffer()

    async def test_emit_outside_buffer_publishes_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        producer = RecordingProducer()
        monkeypatch.setattr("core.events.producers._event_producer", producer)
        await emit_compensation_recorded(
            employee_id=uuid.uuid4(),
            monthly_salary="2000",
            effective_from="2024-04-01",
            tenant_id=TENANT,
        )
        assert len(producer.published) == 1
        assert producer.published[0][0] == "payroll.compensation.recorded"


class TestDepartmentUpdatedEvent:
    async def test_department_update_emits_changed_fields(self, monkeypatch) -> None:
        producer = RecordingProducer()
        monkeypatch.setattr("core.events.producers._event_producer", producer)
        repo = FakeHrRepository()
        service = DepartmentService(repository=repo, audit=AuditService(FakeAuditRepository()))
        department = await service.create(name="Engineering", tenant_id=TENANT)
        assert department.id is not None

        renamed = ent.Department(
            tenant_id=TENANT,
            name="Platform Engineering",
            manager_employee_id=department.manager_employee_id,
            is_active=department.is_active,
            id=department.id,
        )
        await service.update(renamed)

        assert len(producer.published) == 2  # create + update
        topic, event, key = producer.published[1]
        assert topic == "hr.department.updated"
        assert event.metadata["changed_fields"] == {"name": "Platform Engineering"}
        assert key == str(TENANT)


class TestLeaveCancelledEventPending:
    async def test_pending_cancel_emits_leave_cancelled(self, monkeypatch) -> None:
        producer = RecordingProducer()
        monkeypatch.setattr("core.events.producers._event_producer", producer)
        repo = FakeHrRepository()
        repo.leave_types["annual"] = ent.LeaveType(
            tenant_id=TENANT,
            code="annual",
            name="Annual",
            is_accrual=True,
            accrual_days_per_year=20,
            id=uuid.uuid4(),
        )
        employee_id = uuid.uuid4()
        await repo.create_employee(
            ent.Employee(
                tenant_id=TENANT,
                employee_number="EMP-1",
                first_name="A",
                last_name="B",
                job_title="Engineer",
                hire_date=date(2020, 1, 1),
                employment_status=EmploymentStatus.ACTIVE,
                id=employee_id,
            )
        )
        service = LeaveService(repository=repo, audit=AuditService(FakeAuditRepository()))
        request = await service.request(
            tenant_id=TENANT,
            employee_id=employee_id,
            leave_type="annual",
            start_date=date(2024, 5, 1),
            end_date=date(2024, 5, 2),
        )
        await service.cancel(request_id=request.id, tenant_id=TENANT)

        assert any(topic == "hr.leave.cancelled" for topic, _, _ in producer.published)
        event = producer.published[1][1]
        assert event.event_type == "hr.leave.cancelled"
        assert event.metadata["days"] == 2


class TestCompensationRecordedEvent:
    async def test_record_compensation_emits_compensation_recorded(self, monkeypatch) -> None:
        producer = RecordingProducer()
        monkeypatch.setattr("core.events.producers._event_producer", producer)
        service = PayrollService(
            repository=FakePayrollRepository(),
            leave_ledger=_NoopLedger(),
            audit=AuditService(FakeAuditRepository()),
        )
        await service.record_compensation(
            tenant_id=TENANT,
            employee_id=uuid.uuid4(),
            monthly_salary=Money(Decimal("2000"), "USD"),
            effective_from=date(2024, 4, 1),
        )
        assert len(producer.published) == 1
        topic, event, _ = producer.published[0]
        assert topic == "payroll.compensation.recorded"
        assert event.metadata["monthly_salary"] == "2000"


def _envelope(event_type: str) -> BaseEvent:
    from skyrict_events.base import BaseEvent

    return BaseEvent(event_type=event_type, tenant_id=str(TENANT), metadata={})


class _NoopLedger:
    async def approved_unpaid_days(self, *args, **kwargs) -> int:
        return 0

    async def list_accrual_leave_types(self, tenant_id: uuid.UUID):
        return []

    async def accrue(self, **kwargs):
        return None
