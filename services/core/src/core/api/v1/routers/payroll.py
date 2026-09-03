"""Payroll API endpoints - settings, runs, entries, compensation (HR-BE-002 §7).

Every handler requires a valid access token bound to the routed tenant and
resolves the tenant id from the request context. Service ``ValueError`` results
are translated to RFC 7807 domain errors via :func:`raise_from_service_error`.
"""

from __future__ import annotations

import dataclasses
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_payroll_service,
    get_tenant_id,
    require_permission,
)
from core.api.v1.routers.errors import raise_from_service_error
from core.api.v1.schemas import (
    CompensationCreate,
    CompensationOut,
    EntryAdjustmentIn,
    PayrollEntryOut,
    PayrollRunCreate,
    PayrollRunOut,
    PayrollSettingsIn,
    PayrollSettingsOut,
    RunComputeOut,
    SkippedEmployeeOut,
)
from core.core.constants import PayrollRounding
from core.core.permissions import (
    ERP_PAYROLL_APPROVE,
    ERP_PAYROLL_READ,
    ERP_PAYROLL_WRITE,
)
from core.domain import entities as ent
from core.domain.value_objects import Money
from core.features.payroll.service import PayrollService
from skyrict_common.exceptions import NotFoundError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/payroll", tags=["payroll"])

# Permission singletons (docs/modules/hr-payroll.md §7) - resolved per request.
_require_payroll_read = require_permission(ERP_PAYROLL_READ)
_require_payroll_write = require_permission(ERP_PAYROLL_WRITE)
_require_payroll_approve = require_permission(ERP_PAYROLL_APPROVE)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=ResponseEnvelope[PayrollSettingsOut | None])
async def get_settings(
    current_user: dict[str, Any] = Depends(_require_payroll_read),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollSettingsOut | None]:
    settings = await payroll_svc.get_settings(tenant_id)
    return ResponseEnvelope(
        data=PayrollSettingsOut.from_entity(settings) if settings is not None else None
    )


@router.put("/settings", response_model=ResponseEnvelope[PayrollSettingsOut])
async def update_settings(
    body: PayrollSettingsIn,
    current_user: dict[str, Any] = Depends(_require_payroll_write),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollSettingsOut]:
    existing = await payroll_svc.get_settings(tenant_id)
    settings = ent.PayrollSettings(tenant_id=tenant_id) if existing is None else existing
    changes = body.model_dump(exclude_unset=True)
    if "rounding" in changes and changes["rounding"] is not None:
        changes["rounding"] = PayrollRounding(changes["rounding"])
    settings = dataclasses.replace(settings, **changes)
    updated = await payroll_svc.update_settings(settings, actor_user_id=current_user["user_id"])
    return ResponseEnvelope(
        data=PayrollSettingsOut.from_entity(updated), message="Settings updated"
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post("/runs", response_model=ResponseEnvelope[PayrollRunOut], status_code=201)
async def create_run(
    body: PayrollRunCreate,
    current_user: dict[str, Any] = Depends(_require_payroll_write),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollRunOut]:
    try:
        run = await payroll_svc.create_run(
            tenant_id=tenant_id,
            period_start=body.period_start,
            period_end=body.period_end,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=PayrollRunOut.from_entity(run), message="Payroll run created")


@router.get("/runs", response_model=ResponseEnvelope[list[PayrollRunOut]])
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict[str, Any] = Depends(_require_payroll_read),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[PayrollRunOut]]:
    runs = await payroll_svc.list_runs(tenant_id, status=status, limit=limit, offset=offset)
    return ResponseEnvelope(data=[PayrollRunOut.from_entity(r) for r in runs])


@router.get("/runs/{run_id}", response_model=ResponseEnvelope[PayrollRunOut])
async def get_run(
    run_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_read),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollRunOut]:
    run = await payroll_svc.get_run(run_id, tenant_id=tenant_id)
    if run is None:
        raise NotFoundError(f"payroll run {run_id} not found")
    return ResponseEnvelope(data=PayrollRunOut.from_entity(run))


@router.post("/runs/{run_id}/compute", response_model=ResponseEnvelope[RunComputeOut])
async def compute_run(
    run_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_write),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[RunComputeOut]:
    try:
        result = await payroll_svc.compute_run(
            run_id=run_id,
            tenant_id=tenant_id,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(
        data=RunComputeOut(
            run=PayrollRunOut.from_entity(result.run),
            entries=[PayrollEntryOut.from_entity(e) for e in result.entries],
            skipped=[
                SkippedEmployeeOut(employee_id=employee_id, reason=reason)
                for employee_id, reason in result.skipped
            ],
        ),
        message="Payroll run computed",
    )


@router.post("/runs/{run_id}/approve", response_model=ResponseEnvelope[PayrollRunOut])
async def approve_run(
    run_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_approve),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollRunOut]:
    try:
        run = await payroll_svc.approve_run(
            run_id=run_id,
            tenant_id=tenant_id,
            approved_by=current_user["user_id"],
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=PayrollRunOut.from_entity(run), message="Payroll run approved")


@router.post("/runs/{run_id}/pay", response_model=ResponseEnvelope[PayrollRunOut])
async def mark_paid(
    run_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_approve),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollRunOut]:
    try:
        run = await payroll_svc.mark_paid(
            run_id=run_id,
            tenant_id=tenant_id,
            paid_by=current_user["user_id"],
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=PayrollRunOut.from_entity(run), message="Payroll run paid")


@router.post("/runs/{run_id}/void", response_model=ResponseEnvelope[PayrollRunOut])
async def void_run(
    run_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_payroll_approve),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollRunOut]:
    try:
        run = await payroll_svc.void_run(
            run_id=run_id,
            tenant_id=tenant_id,
            reason="voided via API",
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=PayrollRunOut.from_entity(run), message="Payroll run voided")


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/entries", response_model=ResponseEnvelope[list[PayrollEntryOut]])
async def list_entries(
    run_id: uuid.UUID,
    employee_id: uuid.UUID | None = Query(default=None),
    current_user: dict[str, Any] = Depends(_require_payroll_read),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[PayrollEntryOut]]:
    entries = await payroll_svc.list_entries(run_id, tenant_id=tenant_id, employee_id=employee_id)
    return ResponseEnvelope(data=[PayrollEntryOut.from_entity(e) for e in entries])


@router.patch("/runs/{run_id}/entries/{entry_id}", response_model=ResponseEnvelope[PayrollEntryOut])
async def adjust_entry(
    run_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: EntryAdjustmentIn,
    current_user: dict[str, Any] = Depends(_require_payroll_write),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[PayrollEntryOut]:
    try:
        entry = await payroll_svc.adjust_entry_by_id(
            run_id=run_id,
            entry_id=entry_id,
            tenant_id=tenant_id,
            adjustments=body.adjustments,
            actor_user_id=current_user["user_id"],
        )
    except ValueError as exc:
        raise_from_service_error(exc)
    return ResponseEnvelope(data=PayrollEntryOut.from_entity(entry), message="Entry adjusted")


# ---------------------------------------------------------------------------
# Compensation
# ---------------------------------------------------------------------------


@router.post("/compensation", response_model=ResponseEnvelope[CompensationOut], status_code=201)
async def record_compensation(
    body: CompensationCreate,
    current_user: dict[str, Any] = Depends(_require_payroll_write),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[CompensationOut]:
    compensation = await payroll_svc.record_compensation(
        tenant_id=tenant_id,
        employee_id=body.employee_id,
        monthly_salary=Money(Decimal(body.monthly_salary), body.currency),
        effective_from=body.effective_from,
        actor_user_id=current_user["user_id"],
    )
    return ResponseEnvelope(
        data=CompensationOut.from_entity(compensation), message="Compensation recorded"
    )


@router.get("/compensation", response_model=ResponseEnvelope[list[CompensationOut]])
async def list_compensation(
    employee_id: uuid.UUID = Query(...),
    current_user: dict[str, Any] = Depends(_require_payroll_read),
    payroll_svc: PayrollService = Depends(get_payroll_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[list[CompensationOut]]:
    history = await payroll_svc.list_compensation(employee_id, tenant_id=tenant_id)
    return ResponseEnvelope(data=[CompensationOut.from_entity(c) for c in history])
