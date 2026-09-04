"""Payroll event producers - structured domain events for the payroll feature.

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


async def emit_run_created(
    *,
    run_id: uuid.UUID,
    period_start: str,
    period_end: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.run.created`` (run inserted)."""
    event = BaseEvent(
        event_type="payroll.run.created",
        tenant_id=str(tenant_id),
        metadata={
            "run_id": str(run_id),
            "period_start": period_start,
            "period_end": period_end,
        },
    )
    await apublish("payroll.run.created", event, key=str(tenant_id))


async def emit_run_computed(
    *,
    run_id: uuid.UUID,
    period_start: str,
    period_end: str,
    total_gross: str,
    total_net: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.run.computed`` (compute committed)."""
    event = BaseEvent(
        event_type="payroll.run.computed",
        tenant_id=str(tenant_id),
        metadata={
            "run_id": str(run_id),
            "period_start": period_start,
            "period_end": period_end,
            "total_gross": total_gross,
            "total_net": total_net,
        },
    )
    await apublish("payroll.run.computed", event, key=str(tenant_id))


async def emit_run_approved(
    *,
    run_id: uuid.UUID,
    total_net: str,
    entry_count: int,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.run.approved`` (approval committed)."""
    event = BaseEvent(
        event_type="payroll.run.approved",
        tenant_id=str(tenant_id),
        metadata={
            "run_id": str(run_id),
            "total_net": total_net,
            "entry_count": entry_count,
        },
    )
    await apublish("payroll.run.approved", event, key=str(tenant_id))


async def emit_run_paid(
    *,
    run_id: uuid.UUID,
    total_net: str,
    paid_at: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.run.paid`` (mark-paid committed)."""
    event = BaseEvent(
        event_type="payroll.run.paid",
        tenant_id=str(tenant_id),
        metadata={
            "run_id": str(run_id),
            "total_net": total_net,
            "paid_at": paid_at,
        },
    )
    await apublish("payroll.run.paid", event, key=str(tenant_id))


async def emit_run_voided(
    *,
    run_id: uuid.UUID,
    reason: str | None,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.run.voided`` (void committed)."""
    metadata: dict[str, object] = {"run_id": str(run_id)}
    if reason is not None:
        metadata["reason"] = reason
    event = BaseEvent(
        event_type="payroll.run.voided",
        tenant_id=str(tenant_id),
        metadata=metadata,
    )
    await apublish("payroll.run.voided", event, key=str(tenant_id))


async def emit_entry_adjusted(
    *,
    run_id: uuid.UUID,
    employee_id: uuid.UUID,
    adjustments: dict[str, object],
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.entry.adjusted`` (draft/computed entry adjustment)."""
    event = BaseEvent(
        event_type="payroll.entry.adjusted",
        tenant_id=str(tenant_id),
        metadata={
            "run_id": str(run_id),
            "employee_id": str(employee_id),
            "adjustments": adjustments,
        },
    )
    await apublish("payroll.entry.adjusted", event, key=str(tenant_id))


async def emit_settings_updated(
    *,
    tenant_id: uuid.UUID,
    changed_fields: dict[str, object],
) -> None:
    """Emit ``payroll.settings.updated`` (settings upserted)."""
    event = BaseEvent(
        event_type="payroll.settings.updated",
        tenant_id=str(tenant_id),
        metadata={"changed_fields": changed_fields},
    )
    await apublish("payroll.settings.updated", event, key=str(tenant_id))


async def emit_compensation_recorded(
    *,
    employee_id: uuid.UUID,
    monthly_salary: str,
    effective_from: str,
    tenant_id: uuid.UUID,
) -> None:
    """Emit ``payroll.compensation.recorded`` (compensation written)."""
    event = BaseEvent(
        event_type="payroll.compensation.recorded",
        tenant_id=str(tenant_id),
        metadata={
            "employee_id": str(employee_id),
            "monthly_salary": monthly_salary,
            "effective_from": effective_from,
        },
    )
    await apublish("payroll.compensation.recorded", event, key=str(tenant_id))
