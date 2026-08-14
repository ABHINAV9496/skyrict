"""HR event producers — structured domain events for the HR feature.

Phase-1 policy (docs/modules/hr-payroll.md §2.5): emit events **after commit**.
Each ``emit_*`` function builds the shared ``skyrict_events.BaseEvent`` envelope
and publishes it via the process-wide producer (a structlog stub until Kafka
lands), keyed by tenant. Services call these functions after the repository
returns; the real Kafka producer swaps in behind ``get_event_producer()`` with
no call-site change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.events.producers import apublish
from skyrict_events.base import BaseEvent

if TYPE_CHECKING:
    import uuid


async def emit_department_created(
    *,
    department_id: uuid.UUID,
    tenant_id: uuid.UUID,
    name: str,
) -> None:
    """Emit ``hr.department.created`` (department inserted)."""
    event = BaseEvent(
        event_type="hr.department.created",
        tenant_id=str(tenant_id),
        metadata={"department_id": str(department_id), "name": name},
    )
    await apublish("hr.department.created", event, key=str(tenant_id))


async def emit_department_updated(
    *,
    department_id: uuid.UUID,
    tenant_id: uuid.UUID,
    changed_fields: dict[str, object],
) -> None:
    """Emit ``hr.department.updated`` (department edited)."""
    event = BaseEvent(
        event_type="hr.department.updated",
        tenant_id=str(tenant_id),
        metadata={
            "department_id": str(department_id),
            "changed_fields": changed_fields,
        },
    )
    await apublish("hr.department.updated", event, key=str(tenant_id))


async def emit_employee_created(
    *,
    employee_id: uuid.UUID,
    employee_number: str,
    department_id: uuid.UUID | None,
    status: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.employee.created`` (employee inserted)."""
    metadata: dict[str, object] = {
        "employee_id": str(employee_id),
        "employee_number": employee_number,
        "status": status,
    }
    if department_id is not None:
        metadata["department_id"] = str(department_id)
    event = BaseEvent(
        event_type="hr.employee.created",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("hr.employee.created", event, key=str(tenant_id))


async def emit_employee_onboarded(
    *,
    employee_id: uuid.UUID,
    hire_date: str,
    department_id: uuid.UUID | None,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.employee.onboarded`` (alias of ``.created``; reserved for payroll)."""
    metadata: dict[str, object] = {
        "employee_id": str(employee_id),
        "hire_date": hire_date,
    }
    if department_id is not None:
        metadata["department_id"] = str(department_id)
    event = BaseEvent(
        event_type="hr.employee.onboarded",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("hr.employee.onboarded", event, key=str(tenant_id))


async def emit_employee_updated(
    *,
    employee_id: uuid.UUID,
    tenant_id: uuid.UUID,
    changed_fields: dict[str, object],
) -> None:
    """Emit ``hr.employee.updated`` (employee edited)."""
    event = BaseEvent(
        event_type="hr.employee.updated",
        tenant_id=str(tenant_id),
        metadata={
            "employee_id": str(employee_id),
            "changed_fields": changed_fields,
        },
    )
    await apublish("hr.employee.updated", event, key=str(tenant_id))


async def emit_employee_terminated(
    *,
    employee_id: uuid.UUID,
    termination_date: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.employee.terminated`` (terminate transition)."""
    event = BaseEvent(
        event_type="hr.employee.terminated",
        tenant_id=str(tenant_id),
        metadata={
            "employee_id": str(employee_id),
            "termination_date": termination_date,
        },
    )
    await apublish("hr.employee.terminated", event, key=str(tenant_id))


async def emit_leave_requested(
    *,
    request_id: uuid.UUID,
    employee_id: uuid.UUID,
    leave_type: str,
    days: int,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.leave.requested`` (request inserted)."""
    event = BaseEvent(
        event_type="hr.leave.requested",
        tenant_id=str(tenant_id),
        metadata={
            "request_id": str(request_id),
            "employee_id": str(employee_id),
            "leave_type": leave_type,
            "days": days,
        },
    )
    await apublish("hr.leave.requested", event, key=str(tenant_id))


async def emit_leave_approved(
    *,
    request_id: uuid.UUID,
    employee_id: uuid.UUID,
    leave_type: str,
    days: int,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.leave.approved`` (approval committed)."""
    event = BaseEvent(
        event_type="hr.leave.approved",
        tenant_id=str(tenant_id),
        metadata={
            "request_id": str(request_id),
            "employee_id": str(employee_id),
            "leave_type": leave_type,
            "days": days,
        },
    )
    await apublish("hr.leave.approved", event, key=str(tenant_id))


async def emit_leave_rejected(
    *,
    request_id: uuid.UUID,
    employee_id: uuid.UUID,
    reason: str | None,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.leave.rejected`` (rejection committed)."""
    metadata: dict[str, object] = {
        "request_id": str(request_id),
        "employee_id": str(employee_id),
    }
    if reason is not None:
        metadata["reason"] = reason
    event = BaseEvent(
        event_type="hr.leave.rejected",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("hr.leave.rejected", event, key=str(tenant_id))


async def emit_leave_cancelled(
    *,
    request_id: uuid.UUID,
    employee_id: uuid.UUID,
    leave_type: str,
    days: int,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.leave.cancelled`` (cancellation committed)."""
    event = BaseEvent(
        event_type="hr.leave.cancelled",
        tenant_id=str(tenant_id),
        metadata={
            "request_id": str(request_id),
            "employee_id": str(employee_id),
            "leave_type": leave_type,
            "days": days,
        },
    )
    await apublish("hr.leave.cancelled", event, key=str(tenant_id))


async def emit_leave_balance_adjusted(
    *,
    employee_id: uuid.UUID,
    leave_type: str,
    qty: int,
    reason: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.leave.balance.adjusted`` (manual balance adjustment)."""
    event = BaseEvent(
        event_type="hr.leave.balance.adjusted",
        tenant_id=str(tenant_id),
        metadata={
            "employee_id": str(employee_id),
            "leave_type": leave_type,
            "qty": qty,
            "reason": reason,
        },
    )
    await apublish("hr.leave.balance.adjusted", event, key=str(tenant_id))


async def emit_leave_accrued(
    *,
    employee_id: uuid.UUID,
    leave_type: str,
    leave_year: int,
    qty: int,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``hr.leave.accrued`` (annual accrual written)."""
    event = BaseEvent(
        event_type="hr.leave.accrued",
        tenant_id=str(tenant_id),
        metadata={
            "employee_id": str(employee_id),
            "leave_type": leave_type,
            "leave_year": leave_year,
            "qty": qty,
        },
    )
    await apublish("hr.leave.accrued", event, key=str(tenant_id))
