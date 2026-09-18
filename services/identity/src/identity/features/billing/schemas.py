"""Billing schemas - subscription, plan, plan-update, and Stripe session models.

Used by the billing router (SKY-35) and plan-management UI.  All response
models use snake_case to match the codebase convention; requests use
``_CamelModel`` where the frontend sends camelCase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from identity.features.billing.plans import (
    CURRENCY_LITERAL,
    PLAN_ID_LITERAL,
    SUPPORTED_CURRENCIES,
)


class _CamelModel(BaseModel):
    """Request model that accepts and serializes camelCase JSON keys."""

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=AliasGenerator(validation_alias=to_camel, serialization_alias=to_camel),
    )


# -- Subscription (GET /billing/subscription) ---------------------------------


class SubscriptionResponse(BaseModel):
    """Current subscription state for a tenant (any authenticated member can read)."""

    plan_id: str = Field(..., description="Frontend planId (free when unpaid)")
    plan_tier: str = Field(..., description="DB-canonical plan_tier")
    subscription_status: str = Field(
        ..., description="Lifecycle status (none|trialing|active|past_due|canceled|expired)"
    )
    trial_ends_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the free trial ends (null for legacy tenants)",
    )
    days_remaining: int = Field(
        ..., ge=0, description="Whole days remaining in the current trial (0 if expired/none)"
    )
    billing_email: str | None = Field(default=None, description="Tenant billing email")

    model_config = {"from_attributes": True}


# -- Plan (GET /billing/plan) -------------------------------------------------


class PlanLimitsResponse(BaseModel):
    """Feature limits for a billing plan."""

    max_users: int | None = Field(
        default=None, description="Maximum workspace members (None = unlimited)"
    )
    ai_credits_monthly: int | None = Field(
        default=None, description="Monthly AI credit budget (None = custom)"
    )
    max_agents: int | None = Field(default=None, description="Maximum AI agents (None = unlimited)")
    modules: list[str] = Field(default_factory=list, description="Included platform modules")


class PlanPriceResponse(BaseModel):
    """Fixed price point for one currency in a plan."""

    currency: str = Field(..., description="ISO 4217 currency code")
    monthly_cents: int | None = Field(
        default=None, description="Monthly price in currency cents (None = custom)"
    )
    annual_cents: int | None = Field(
        default=None,
        description="Annual monthly-equivalent price in currency cents (None = custom)",
    )
    display_locale: str = Field(
        default="en-US", description="BCP-47 locale used to render this price in the UI"
    )


class PlanResponse(BaseModel):
    """API response for a single billing plan."""

    id: str = Field(..., description="Frontend planId")
    tier: str = Field(..., description="DB-canonical plan_tier")
    display_name: str = Field(..., description="Human-readable plan name")
    monthly_price_cents: int | None = Field(
        default=None, description="Monthly price in USD cents (None = custom)"
    )
    annual_price_cents: int | None = Field(
        default=None, description="Annual monthly-equivalent price in USD cents (None = custom)"
    )
    prices: dict[str, PlanPriceResponse] = Field(
        default_factory=dict, description="Per-currency fixed price points"
    )
    features: PlanLimitsResponse = Field(default_factory=PlanLimitsResponse)

    model_config = {"from_attributes": True}


# -- Plan update (PATCH /billing/plan) ----------------------------------------


class PlanUpdateRequest(_CamelModel):
    """PATCH /billing/plan — switch the tenant's paid plan (owner-only)."""

    plan_id: PLAN_ID_LITERAL = Field(..., description="Target plan to switch to")


# -- Stripe sessions (BILLING-UI-004) ----------------------------------------


class CheckoutSessionRequest(_CamelModel):
    """POST /billing/checkout-session — start a Stripe Checkout for a plan."""

    plan_id: PLAN_ID_LITERAL = Field(..., description="Paid plan to subscribe to")
    interval: Literal["month", "year"] = Field(
        default="month", description="Billing interval (monthly or annual)"
    )
    currency: CURRENCY_LITERAL = Field(
        default="usd",
        description=(
            "Currency for the billed price. Selects a currency-specific Stripe "
            "Price; falls back to USD when none is configured. "
            f"Supported: {', '.join(SUPPORTED_CURRENCIES)}."
        ),
    )


class CheckoutSessionResponse(BaseModel):
    """Stripe Checkout session — the client redirects the browser to ``url``."""

    session_id: str = Field(..., description="Stripe Checkout Session id (cs_...)")
    url: str = Field(..., description="Stripe-hosted checkout URL to redirect to")


class PortalSessionResponse(BaseModel):
    """Stripe Customer Portal session — manage payment methods, invoices, plan."""

    session_id: str = Field(..., description="Stripe Billing Portal Session id")
    url: str = Field(..., description="Stripe-hosted portal URL to redirect to")


# -- Stripe webhook + tick (BILLING-SERV-002) -----------------------------------


class WebhookAckResponse(BaseModel):
    """Ack returned to Stripe for a signature-valid webhook delivery."""

    status: str = Field(
        ...,
        description="Outcome: applied (state changed) | skipped (duplicate) | ignored (unhandled type)",
    )


class TickResponse(BaseModel):
    """Result of an explicit lazy-check tick (ops/cron)."""

    tenant_id: str = Field(..., description="Tenant the tick ran against")
    checked: bool = Field(default=True, description="True when the tick ran")
    changed: bool = Field(
        ..., description="True when the tick mutated subscription state (e.g. grace downgrade)"
    )
