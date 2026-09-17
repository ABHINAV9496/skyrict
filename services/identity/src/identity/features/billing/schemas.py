"""Billing schemas - subscription, plan, and plan-update request models.

Used by the billing router (SKY-35) and plan-management UI.  All response
models use snake_case to match the codebase convention; requests use
``_CamelModel`` where the frontend sends camelCase.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import AliasGenerator, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from identity.features.billing.plans import PLAN_ID_LITERAL


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
    features: PlanLimitsResponse = Field(default_factory=PlanLimitsResponse)

    model_config = {"from_attributes": True}


# -- Plan update (PATCH /billing/plan) ----------------------------------------


class PlanUpdateRequest(_CamelModel):
    """PATCH /billing/plan — switch the tenant's paid plan (owner-only)."""

    plan_id: PLAN_ID_LITERAL = Field(..., description="Target plan to switch to")
