"""Server-side billing plan catalog and tier mapping (SKY-33 / ADR-009).

``PLAN_ID_MAP`` is the single source of truth for the bidirectional mapping
between the frontend ``planId`` values (``starter``, ``professional``,
``business``, ``enterprise``) and the DB-canonical ``plan_tier`` values
(``free``, ``starter``, ``pro``, ``business``, ``enterprise``).

The catalog exposes four paid tiers with monthly/annual pricing (in USD
cents to avoid float arithmetic) and typed feature limits.  The ``free``
tier is the implicit default (not a purchasable catalog entry).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# -- Plan ID / tier mapping ---------------------------------------------------

#: Frontend planId → DB plan_tier.
PLAN_ID_MAP: dict[str, str] = {
    "starter": "starter",
    "professional": "pro",
    "business": "business",
    "enterprise": "enterprise",
}

#: DB plan_tier → frontend planId (reverse lookup).
TIER_MAP: dict[str, str] = {v: k for k, v in PLAN_ID_MAP.items()}

PLAN_ID_LITERAL = Literal["starter", "professional", "business", "enterprise"]


def resolve_tier(plan_id: str) -> str:
    """Map a frontend planId to the canonical DB plan_tier."""
    return PLAN_ID_MAP.get(plan_id, plan_id)


def resolve_plan_id(tier: str) -> str:
    """Map a DB plan_tier to the frontend planId."""
    return TIER_MAP.get(tier, tier)


# -- Feature limits -----------------------------------------------------------


class PlanLimits(BaseModel):
    """Typed feature limits for a billing plan."""

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


# -- Plan catalog ------------------------------------------------------------


class Plan(BaseModel):
    """One entry in the server-side plan catalog.

    Prices are stored as **USD cents** (int) to preserve exact arithmetic.
    ``None`` means custom pricing (Enterprise).
    """

    id: str = Field(..., description="Frontend planId (starter|professional|business|enterprise)")
    tier: str = Field(..., description="DB-canonical plan_tier")
    display_name: str = Field(..., description="Human-readable plan name")
    monthly_price_cents: int | None = Field(
        default=None, description="Monthly price in USD cents (None = custom)"
    )
    annual_price_cents: int | None = Field(
        default=None, description="Annual monthly-equivalent price in USD cents (None = custom)"
    )
    features: PlanLimits = Field(default_factory=PlanLimits)


_starters_modules = [
    "Core ERP slice (inventory, sales, cash, orders)",
    "Market intel - 1 signal source",
    "1 agent",
    "Email verification & MFA",
]

_professional_modules = [
    "Everything in Starter",
    "All 5 market signal sources",
    "5 agents",
    "API access",
]

_business_modules = [
    "Everything in Professional",
    "Agent autopilot (auto-actions)",
    "Unlimited agents",
    "Advanced permissions",
]

_enterprise_modules = [
    "Everything in Business",
    "SSO / SAML",
    "Custom data integrations",
    "Dedicated infrastructure",
]

PLANS: dict[str, Plan] = {
    "starter": Plan(
        id="starter",
        tier="starter",
        display_name="Starter",
        monthly_price_cents=0,
        annual_price_cents=0,
        features=PlanLimits(
            max_users=1,
            ai_credits_monthly=500,
            max_agents=1,
            modules=_starters_modules,
        ),
    ),
    "professional": Plan(
        id="professional",
        tier="pro",
        display_name="Professional",
        monthly_price_cents=2_900,
        annual_price_cents=2_400,
        features=PlanLimits(
            max_users=5,
            ai_credits_monthly=5_000,
            max_agents=5,
            modules=_professional_modules,
        ),
    ),
    "business": Plan(
        id="business",
        tier="business",
        display_name="Business",
        monthly_price_cents=7_900,
        annual_price_cents=6_600,
        features=PlanLimits(
            max_users=20,
            ai_credits_monthly=20_000,
            max_agents=None,
            modules=_business_modules,
        ),
    ),
    "enterprise": Plan(
        id="enterprise",
        tier="enterprise",
        display_name="Enterprise",
        monthly_price_cents=None,
        annual_price_cents=None,
        features=PlanLimits(
            max_users=None,
            ai_credits_monthly=None,
            max_agents=None,
            modules=_enterprise_modules,
        ),
    ),
}
