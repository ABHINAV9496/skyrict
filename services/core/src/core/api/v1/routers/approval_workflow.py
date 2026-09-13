"""Approval workflow API - inbox, instance detail and decisions (SKY-92).

The inbox answers "what needs my attention" for the signed-in user: pending
steps on which the user is a direct assignee (role / permission / explicit
user list) or an active delegate. Eligibility is resolved live from the DB at
request time using the exact probes the engine uses at decision time, so a
revoked role or delegation disappears immediately.

Decisions are delegated to ``ApprovalEngine.decide`` which owns every
validation (instance pending, step pending/escalated, actor membership in the
resolved assignee set or active delegation) and every write (step decision +
append-only transition + instance advancement). The engine's resource port
dispatches completed instances to the owning module's authoritative state
transition on the same request-scoped session.

Permission gate: the caller must hold ``erp.finance.approve`` OR
``erp.payroll.approve`` (the two module keys whose resources flow through the
engine today). The engine then re-checks step membership - a coarse gate here
never substitutes for the step's own assignee set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from core.api.deps import (
    get_approval_decision_engine,
    get_approval_query_service,
    get_tenant_id,
    require_any_permission,
)
from core.api.v1.schemas.approval_workflow import (
    ApprovalDecisionIn,
    ApprovalDecisionOut,
    ApprovalInboxItemOut,
    ApprovalInstanceOut,
)
from core.core.permissions import ERP_FINANCE_APPROVE, ERP_PAYROLL_APPROVE
from core.features.approval_workflow.engine import ApprovalEngine
from core.features.approval_workflow.query import ApprovalWorkflowQueryService
from skyrict_common.exceptions import NotFoundError
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/approval", tags=["approval-workflow"])

# Coarse access gate: module approve keys whose resources run through the
# engine. The engine re-checks step membership at decision time.
_require_approval_access = require_any_permission(ERP_FINANCE_APPROVE, ERP_PAYROLL_APPROVE)


@router.get("/inbox", response_model=ResponseEnvelope[list[ApprovalInboxItemOut]])
async def list_inbox(
    current_user: dict[str, Any] = Depends(_require_approval_access),
    query_svc: ApprovalWorkflowQueryService = Depends(get_approval_query_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    limit: int = Query(default=100, ge=1, le=200),
) -> ResponseEnvelope[list[ApprovalInboxItemOut]]:
    entries = await query_svc.list_inbox(
        tenant_id=tenant_id,
        user_id=current_user["user_id"],
        now=datetime.now(UTC),
        limit=limit,
    )
    return ResponseEnvelope(data=[ApprovalInboxItemOut.from_entry(entry) for entry in entries])


@router.get("/inbox/{instance_id}", response_model=ResponseEnvelope[ApprovalInstanceOut])
async def get_instance(
    instance_id: uuid.UUID,
    current_user: dict[str, Any] = Depends(_require_approval_access),
    query_svc: ApprovalWorkflowQueryService = Depends(get_approval_query_service),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[ApprovalInstanceOut]:
    view = await query_svc.get_instance(tenant_id=tenant_id, instance_id=instance_id)
    if view is None:
        raise NotFoundError(f"Approval instance {instance_id} not found")
    return ResponseEnvelope(data=ApprovalInstanceOut.from_view(view))


@router.post(
    "/inbox/{instance_id}/decide",
    response_model=ResponseEnvelope[ApprovalDecisionOut],
)
async def decide(
    instance_id: uuid.UUID,
    body: ApprovalDecisionIn,
    current_user: dict[str, Any] = Depends(_require_approval_access),
    engine: ApprovalEngine = Depends(get_approval_decision_engine),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
) -> ResponseEnvelope[ApprovalDecisionOut]:
    result = await engine.decide(
        tenant_id=tenant_id,
        instance_id=instance_id,
        actor_id=current_user["user_id"],
        decision=body.decision,
        reason=body.reason,
    )
    return ResponseEnvelope(
        data=ApprovalDecisionOut.from_result(result),
        message="Decision recorded",
    )


__all__ = ["router"]
