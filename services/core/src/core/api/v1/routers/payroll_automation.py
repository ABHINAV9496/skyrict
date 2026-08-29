"""Payroll automation API — batch enqueue, status, and manual/CI tick (HR-AUT-001).

Every handler requires an access token bound to the routed tenant and the
``erp.payroll.ai.*`` permission; service ``ValueError`` results are translated
to RFC 7807 domain errors via :func:`raise_from_service_error`. The background
worker (``api/lifespan.py``) is the always-on drain; ``POST /tick`` is the
deterministic, testable way to advance the queue.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends

from core.api.deps import (
    get_payroll_automation_service,
    get_tenant_id,
    require_permission,
)
from core.api.v1.routers.errors import raise_from_service_error
from core.api.v1.schemas import (
    PayrollBatchEnqueueRequest,
    PayrollBatchOut,
    PayrollBatchTickOut,
)
from core.core.permissions import ERP_PAYROLL_AI_READ, ERP_PAYROLL_AI_RUN
from core.features.payroll_automation.service import PayrollAutomationService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/ai/payroll", tags=["ai", "payroll"])

_require_payroll_ai_read = require_permission(ERP_PAYROLL_AI_READ)
_require_payroll_ai_run = require_permission(ERP_PAYROLL_AI_RUN)


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
        message=f"Enqueued payroll batch for {result.employee_count} employees",
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
) -> ResponseEnvelope[PayrollBatchTickOut]:
    result = await payroll_ai_svc.process_once(actor_user_id=current_user["user_id"])
    return ResponseEnvelope(
        data=PayrollBatchTickOut(
            batch_id=result.batch_id,
            items_processed=result.items_processed,
            status_changed=result.status_changed,
        )
    )
