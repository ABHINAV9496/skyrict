"""Payroll automation API — batch enqueue, status, manual/CI tick, schedules,
notifications (HR-AUT-001).

Every handler requires an access token bound to the routed tenant and an
``erp.payroll.ai.*`` permission; service ``ValueError`` results are translated
to RFC 7807 domain errors via :func:`raise_from_service_error`. The background
worker (``api/lifespan.py``) is the always-on drain; ``POST /tick`` is the
deterministic, testable way to advance the queue (and to fire due schedules).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_payroll_automation_service,
    get_payroll_notification_orchestrator,
    get_payroll_scheduler_service,
    get_tenant_id,
    require_permission,
)
from core.api.v1.routers.errors import raise_from_service_error
from core.api.v1.schemas import (
    PayrollBatchEnqueueRequest,
    PayrollBatchListItem,
    PayrollBatchOut,
    PayrollBatchTickOut,
    PayrollNotificationOut,
    PayrollPreferencesIn,
    PayrollPreferencesOut,
    PayrollScheduleIn,
    PayrollScheduleOut,
)
from core.core.permissions import (
    ERP_PAYROLL_AI_NOTIFY,
    ERP_PAYROLL_AI_READ,
    ERP_PAYROLL_AI_RUN,
)
from core.features.payroll_automation.notifications import PayrollNotificationOrchestrator
from core.features.payroll_automation.schedules import PayrollSchedulerService
from core.features.payroll_automation.service import PayrollAutomationService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/ai/payroll", tags=["ai", "payroll"])

_require_payroll_ai_read = require_permission(ERP_PAYROLL_AI_READ)
_require_payroll_ai_run = require_permission(ERP_PAYROLL_AI_RUN)
_require_payroll_ai_notify = require_permission(ERP_PAYROLL_AI_NOTIFY)


def _schedule_out(schedule: object) -> PayrollScheduleOut:
    return PayrollScheduleOut(
        schedule_id=schedule.id,
        tenant_id=schedule.tenant_id,
        name=schedule.name,
        cron_expression=schedule.cron_expression,
        enabled=schedule.enabled,
        last_fired_at=schedule.last_fired_at,
        next_run_at=schedule.next_run_at,
    )


@router.post(
    "/batches",
    response_model=ResponseEnvelope[PayrollBatchOut],
    status_code=201,
)
async def enqueue_batch(
    body: PayrollBatchEnqueueRequest,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_run),
    payroll_ai_svc: PayrollAutomationService = Depends(get_payroll_automation_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollBatchOut]:
    try:
        result = await payroll_ai_svc.enqueue(
            run_id=body.run_id,
            tenant_id=tenant_id,
            actor_user_id=current_user["user_id"],
            dry_run=body.dry_run,
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    status = result.batch.status
    if status == "aborted":
        blocks = (result.batch.preflight or {}).get("blocks", [])
        message = f"Payroll batch blocked by pre-flight checks: {', '.join(blocks)}"
    else:
        message = f"Enqueued payroll batch for {result.employee_count} employees"
    return ResponseEnvelope(
        data=PayrollBatchOut(
            batch_id=result.batch.id,
            tenant_id=result.batch.tenant_id,
            source=result.batch.source,
            source_ref=result.batch.source_ref,
            status=result.batch.status,
            dry_run=result.batch.dry_run,
            claimed_by=result.batch.claimed_by,
            preflight=result.batch.preflight,
            totals=result.batch.totals or {},
            started_at=result.batch.started_at,
            finished_at=result.batch.finished_at,
        ),
        message=message,
    )


@router.get("/batches", response_model=ResponseEnvelope[list[PayrollBatchListItem]])
async def list_batches(
    status: str | None = Query(None, description="Filter by batch status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict[str, Any] = Depends(_require_payroll_ai_read),
    payroll_ai_svc: PayrollAutomationService = Depends(get_payroll_automation_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[PayrollBatchListItem]]:
    batches = await payroll_ai_svc.list_batches(
        tenant_id=tenant_id, status=status, limit=limit, offset=offset
    )
    return ResponseEnvelope(
        data=[PayrollBatchListItem(**batch) for batch in batches],
        message=f"Listed {len(batches)} payroll batches",
    )


@router.get("/batches/{batch_id}", response_model=ResponseEnvelope[PayrollBatchOut])
async def get_batch(
    batch_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_read),
    payroll_ai_svc: PayrollAutomationService = Depends(get_payroll_automation_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollBatchOut]:
    try:
        status = await payroll_ai_svc.batch_status(batch_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=PayrollBatchOut(**status))


@router.post("/tick", response_model=ResponseEnvelope[PayrollBatchTickOut])
async def manual_tick(
    current_user: dict[str, Any] = Depends(_require_payroll_ai_run),
    payroll_ai_svc: PayrollAutomationService = Depends(get_payroll_automation_service),
    scheduler: PayrollSchedulerService = Depends(get_payroll_scheduler_service),
) -> ResponseEnvelope[PayrollBatchTickOut]:
    fired = await scheduler.run_due_schedules()
    result = await payroll_ai_svc.process_once(actor_user_id=current_user["user_id"])
    return ResponseEnvelope(
        data=PayrollBatchTickOut(
            batch_id=result.batch_id,
            items_processed=result.items_processed,
            status_changed=result.status_changed,
            schedules_fired=fired,
        )
    )


# ---------------------------------------------------------------------------
# Schedules (HR-AUT-001 §5.8 recurring submissions)
# ---------------------------------------------------------------------------


@router.post(
    "/schedules",
    response_model=ResponseEnvelope[PayrollScheduleOut],
    status_code=201,
)
async def create_schedule(
    body: PayrollScheduleIn,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_run),
    scheduler: PayrollSchedulerService = Depends(get_payroll_scheduler_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollScheduleOut]:
    try:
        schedule = await scheduler.create_schedule(
            tenant_id=tenant_id,
            cron_expression=body.cron_expression,
            name=body.name,
            enabled=body.enabled,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=_schedule_out(schedule),
        message="Created payroll schedule",
    )


@router.get("/schedules", response_model=ResponseEnvelope[list[PayrollScheduleOut]])
async def list_schedules(
    current_user: dict[str, Any] = Depends(_require_payroll_ai_read),
    scheduler: PayrollSchedulerService = Depends(get_payroll_scheduler_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[PayrollScheduleOut]]:
    schedules = await scheduler.list_schedules(tenant_id=tenant_id)
    return ResponseEnvelope(
        data=[_schedule_out(schedule) for schedule in schedules],
        message=f"Listed {len(schedules)} payroll schedules",
    )


@router.get("/schedules/{schedule_id}", response_model=ResponseEnvelope[PayrollScheduleOut])
async def get_schedule(
    schedule_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_read),
    scheduler: PayrollSchedulerService = Depends(get_payroll_scheduler_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollScheduleOut]:
    schedule = await scheduler.get_schedule(schedule_id, tenant_id=tenant_id)
    if schedule is None:
        raise_from_service_error(ValueError(f"payroll schedule {schedule_id} not found"))
    return ResponseEnvelope(
        data=_schedule_out(schedule),
        message="Fetched payroll schedule",
    )


@router.patch("/schedules/{schedule_id}", response_model=ResponseEnvelope[PayrollScheduleOut])
async def update_schedule(
    schedule_id: uuid.UUID,
    body: PayrollScheduleIn,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_run),
    scheduler: PayrollSchedulerService = Depends(get_payroll_scheduler_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollScheduleOut]:
    try:
        schedule = await scheduler.update_schedule(
            schedule_id,
            tenant_id=tenant_id,
            cron_expression=body.cron_expression,
            name=body.name,
            enabled=body.enabled,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=_schedule_out(schedule),
        message="Updated payroll schedule",
    )


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_run),
    scheduler: PayrollSchedulerService = Depends(get_payroll_scheduler_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[dict[str, object]]:
    try:
        await scheduler.delete_schedule(schedule_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data={}, message="Deleted payroll schedule")


# ---------------------------------------------------------------------------
# Notifications + delivery preferences
# ---------------------------------------------------------------------------


@router.get("/notifications", response_model=ResponseEnvelope[list[PayrollNotificationOut]])
async def list_notifications(
    event_type: str | None = Query(None, description="payslip_ready | payroll_batch_digest"),
    after: datetime | None = Query(None),
    before: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict[str, Any] = Depends(_require_payroll_ai_read),
    orchestrator: PayrollNotificationOrchestrator = Depends(get_payroll_notification_orchestrator),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[PayrollNotificationOut]]:
    rows = await orchestrator.list_notifications(
        tenant_id=tenant_id,
        event_type=event_type,
        after=after,
        before=before,
        limit=limit,
    )
    return ResponseEnvelope(
        data=[PayrollNotificationOut(**row) for row in rows],
        message=f"Listed {len(rows)} payroll notifications",
    )


@router.get(
    "/notifications/preferences",
    response_model=ResponseEnvelope[PayrollPreferencesOut],
)
async def get_preferences(
    current_user: dict[str, Any] = Depends(_require_payroll_ai_notify),
    orchestrator: PayrollNotificationOrchestrator = Depends(get_payroll_notification_orchestrator),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollPreferencesOut]:
    prefs = await orchestrator.get_pref(tenant_id=tenant_id, user_id=current_user["user_id"])
    return ResponseEnvelope(data=PayrollPreferencesOut(**prefs), message="Fetched preferences")


@router.put(
    "/notifications/preferences",
    response_model=ResponseEnvelope[PayrollPreferencesOut],
)
async def update_preferences(
    body: PayrollPreferencesIn,
    current_user: dict[str, Any] = Depends(_require_payroll_ai_notify),
    orchestrator: PayrollNotificationOrchestrator = Depends(get_payroll_notification_orchestrator),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollPreferencesOut]:
    prefs = await orchestrator.upsert_pref(
        tenant_id=tenant_id,
        user_id=current_user["user_id"],
        in_app_on=body.in_app_on,
        email_on=body.email_on,
    )
    return ResponseEnvelope(data=PayrollPreferencesOut(**prefs), message="Updated preferences")
