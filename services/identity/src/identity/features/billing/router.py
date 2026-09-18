"""Billing endpoints - subscription state, plan management, catalog.

Route guards mirror the ticket semantics:
  * ``GET /billing/subscription`` — any authenticated tenant member.
  * ``GET /billing/plan`` and ``PATCH /billing/plan`` — tenant owner only
    (``billing.manage`` permission + ``tenant_owner`` role).
  * ``GET /billing/plans`` — any authenticated tenant member (catalog).
  * ``GET /billing/signup/plans`` — PUBLIC (the pre-login signup wizard
    Plan step runs before an account exists; same catalog as above).
  * ``POST /billing/checkout-session`` and ``POST /billing/portal-session`` —
    tenant owner only; owner-only because they mint Stripe sessions that can
    charge the workspace card.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from identity.api.deps import (
    get_billing_service,
    get_current_user,
    get_stripe_client,
    require_billing_owner,
)
from identity.core.stripe import InvalidSignatureError, StripeClient
from identity.core.tenant_context import get_current_tenant
from identity.features.billing.schemas import (
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    PlanResponse,
    PlanUpdateRequest,
    PortalSessionResponse,
    SubscriptionResponse,
    TickResponse,
    WebhookAckResponse,
)
from identity.features.billing.service import BillingService
from skyrict_common.exceptions import AuthenticationError
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


@router.get("/signup/plans", response_model=ResponseEnvelope[list[PlanResponse]])
async def list_signup_plans(
    billing_svc: BillingService = Depends(get_billing_service),
) -> ResponseEnvelope[list[PlanResponse]]:
    """Return the plan catalog for the pre-login signup wizard (public).

    The signup Plan step runs before the owner has any account, so this
    endpoint deliberately carries NO auth dependency. It serves the exact same
    server-side catalog as ``GET /billing/plans`` - the frontend never
    hardcodes prices. Only catalog data leaves the service; no tenant or
    subscription state is exposed.
    """
    plans = await billing_svc.list_plans()
    return ResponseEnvelope(data=[_as_plan_response(p) for p in plans])


@router.post("/checkout-session", response_model=ResponseEnvelope[CheckoutSessionResponse])
async def start_checkout(
    body: CheckoutSessionRequest,
    current_user: dict[str, Any] = Depends(_require_billing_owner),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[CheckoutSessionResponse]:
    """Create a Stripe Checkout session for a paid plan upgrade (owner only).

    Returns a Stripe-hosted ``url`` the owner's browser redirects to. When
    Stripe is not configured the endpoint returns a sanitized 503; plans
    without a configured Stripe Price (Starter, custom-priced Enterprise)
    return 422.
    """
    session = await billing_svc.create_checkout_session(
        tenant_id, body.plan_id, body.interval, body.currency
    )
    return ResponseEnvelope(data=CheckoutSessionResponse.model_validate(session))


@router.post("/portal-session", response_model=ResponseEnvelope[PortalSessionResponse])
async def create_billing_portal(
    current_user: dict[str, Any] = Depends(_require_billing_owner),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[PortalSessionResponse]:
    """Create a Stripe Customer Portal session to manage billing (owner only).

    Returns a Stripe-hosted ``url`` the owner's browser redirects to. A tenant
    that has never checked out (no Stripe customer) gets 402.
    """
    session = await billing_svc.create_portal_session(tenant_id)
    return ResponseEnvelope(data=PortalSessionResponse.model_validate(session))


@router.post("/webhooks", response_model=ResponseEnvelope[WebhookAckResponse])
async def receive_webhook(
    request: Request,
    billing_svc: BillingService = Depends(get_billing_service),
    stripe_client: StripeClient = Depends(get_stripe_client),
) -> ResponseEnvelope[WebhookAckResponse]:
    """Receive a Stripe lifecycle event (signature IS the authentication).

    The Stripe signature over the raw body is verified before anything is
    processed - there is no bearer token on Stripe webhooks. On failure the
    handler raises 401 and Stripe retries; on success it acks and Stripe
    stops delivering. Duplicate deliveries are acknowledged and skipped by the
    idempotency store, never double-applied.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.construct_event(payload, signature)
    except InvalidSignatureError as exc:
        raise AuthenticationError("Invalid Stripe webhook signature") from exc

    status = await billing_svc.handle_stripe_event(
        event_id=event.id,
        event_type=event.type,
        event_object=dict(event.data.object),
    )
    return ResponseEnvelope(data=WebhookAckResponse(status=status))


@router.post("/tick", response_model=ResponseEnvelope[TickResponse])
async def billing_tick(
    current_user: dict[str, Any] = Depends(_require_billing_owner),
    billing_svc: BillingService = Depends(get_billing_service),
    tenant_id: str = Depends(get_current_tenant),
) -> ResponseEnvelope[TickResponse]:
    """Explicit lazy-check trigger (ops/cron) - same path as subscription reads.

    Runs trial-expiry and grace-expiry checks now and reports whether state
    changed, so a scheduler can invoke this on an interval instead of relying
    on a read occurring. Mirrors the payroll tick precedent.
    """
    result = await billing_svc.tick(tenant_id)
    return ResponseEnvelope(data=TickResponse.model_validate(result))
