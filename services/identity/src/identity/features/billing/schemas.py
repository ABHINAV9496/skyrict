"""Billing schemas - catalog plan response models (SKY-33).

Used by the future BILLING-API-003 plan-read endpoint and BILLING-UI-004
plan-management UI.  The schema contract is established here so frontend
and backend can evolve independently.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanLimitsResponse(BaseModel):
    """Feature limits for a billing plan."""

    max_users: int | None = Field(
        default=None, description="Maximum workspace members (None = unlimited)"
    )
    ai_credits_monthly: int | None = Field(
        default=None, description="Monthly AI credit budget (None = custom)"
    )
    max_agents: int | None = Field(
        default=None, description="Maximum AI agents (None = unlimited)"
    )
    modules: list[str] = Field(
        default_factory=list, description="Included platform modules"
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
    features: PlanLimitsResponse = Field(default_factory=PlanLimitsResponse)

    model_config = {"from_attributes": True}
