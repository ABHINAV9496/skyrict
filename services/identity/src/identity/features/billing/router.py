"""Billing endpoints - subscription state, plan management, catalog.

Route guards mirror the ticket semantics:
  * ``GET /billing/subscription`` — any authenticated tenant member.
  * ``GET /billing/plan`` and ``PATCH /billing/plan`` — tenant owner only
    (``billing.manage`` permission + ``tenant_owner`` role).
  * ``GET /billing/plans`` — any authenticated tenant member (catalog).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from identity.api.deps import get_billing_service, get_current_user, require_billing_owner
from identity.core.tenant_context import get_current_tenant
from identity.features.billing.schemas import (
    PlanResponse,
    PlanUpdateRequest,
    SubscriptionResponse,
)
from identity.features.billing.service import BillingService
from skyrict_common.schemas import ResponseEnvelope

router = APIRouter(prefix="/billing", tags=["billing"])

_require_billing_owner = require_billing_owner()


def _as_plan_response(catalog_entry: dict[str, Any]) -> PlanResponse:
    """Validate/unwrap a catalog entry dict into the PlanResponse contract."""
    return PlanResponse.model_validate(catalog_entry)


@router.get("/subscription", response_model=ResponseEnvelope[SubscriptionResponse])
async def get_subscription(
    current_user: dict[str, Any] = Depends(get_current_user),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[SubscriptionResponse]:
    """Return the current tenant's subscription + trial state (owner + members)."""
    state = await billing_svc.get_subscription(tenant_id)
    return ResponseEnvelope(data=SubscriptionResponse.model_validate(state))


@router.get("/plan", response_model=ResponseEnvelope[PlanResponse])
async def get_plan(
    current_user: dict[str, Any] = Depends(_require_billing_owner),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[PlanResponse]:
    """Return the tenant's current plan (owner only)."""
    plan = await billing_svc.get_plan(tenant_id)
    return ResponseEnvelope(data=_as_plan_response(plan))


@router.patch("/plan", response_model=ResponseEnvelope[PlanResponse])
async def update_plan(
    body: PlanUpdateRequest,
    current_user: dict[str, Any] = Depends(_require_billing_owner),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[PlanResponse]:
    """Switch the tenant's plan.  Validates against the catalog (422 on unknown plan)."""
    plan = await billing_svc.update_plan(tenant_id, body.plan_id)
    return ResponseEnvelope(
        data=_as_plan_response(plan), message=f"Plan switched to {plan['display_name']}"
    )


@router.get("/plans", response_model=ResponseEnvelope[list[PlanResponse]])
async def list_plans(
    current_user: dict[str, Any] = Depends(get_current_user),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[list[PlanResponse]]:
    """Return the full plan catalog in canonical order (any authenticated member)."""
    plans = await billing_svc.list_plans()
    return ResponseEnvelope(data=[_as_plan_response(p) for p in plans])
