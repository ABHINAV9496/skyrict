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

# -- Currencies --------------------------------------------------------------

#: Beta checkout allowlist (SKY-40). Exactly these markets can complete
#: checkout; every other country is region-blocked at the pricing page and
#: rejected server-side at the checkout API. Fixed per-currency price points
#: are set manually (reviewed for market fit) - never derived from a live FX
#: rate. Do NOT grow this tuple without a business-approved price table.
SUPPORTED_CURRENCIES: tuple[str, ...] = (
    "usd",
    "inr",
    "gbp",
    "eur",
    "aud",
    "cad",
    "sgd",
    "aed",
    "sar",
)

CURRENCY_LITERAL = Literal[
    "usd", "inr", "gbp", "eur", "aud", "cad", "sgd", "aed", "sar"
]

#: Allowlisted markets whose fixed price points have NOT been approved yet.
#: They resolve to their local currency for messaging, but checkout is
#: rejected server-side (no USD catch-all) and they carry no price rows in
#: the catalog. Move a code out of here ONLY together with its price rows
#: in ``_CURRENCY_PRICES`` - the CI coverage test enforces the pairing.
PRICING_PENDING_CURRENCIES: tuple[str, ...] = ("aed", "sar")

#: Currencies with complete, business-approved fixed price points.
PRICED_CURRENCIES: tuple[str, ...] = tuple(
    code for code in SUPPORTED_CURRENCIES if code not in PRICING_PENDING_CURRENCIES
)

#: BCP-47 display locale used to format prices for a currency (en-IN gives
#: lakh-style grouping, e.g. "₹1,99,900").
CURRENCY_LOCALES: dict[str, str] = {
    "usd": "en-US",
    "inr": "en-IN",
    "gbp": "en-GB",
    "eur": "de-DE",
    "aud": "en-AU",
    "cad": "en-CA",
    "sgd": "en-SG",
    "aed": "en-AE",
    "sar": "ar-SA",
}


def resolve_currency(currency: str) -> str | None:
    """Normalize a currency code to the catalog; None for unsupported values."""
    code = currency.strip().lower()
    return code if code in SUPPORTED_CURRENCIES else None


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
    max_agents: int | None = Field(default=None, description="Maximum AI agents (None = unlimited)")
    modules: list[str] = Field(default_factory=list, description="Included platform modules")


# -- Plan catalog ------------------------------------------------------------


class PlanPrice(BaseModel):
    """Fixed price point for one currency.

    Amounts are stored as **cents of the currency** (int) to preserve exact
    arithmetic. ``None`` means custom pricing (Enterprise) - the plan is not
    purchasable via Checkout in that currency.
    """

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


class Plan(BaseModel):
    """One entry in the server-side plan catalog.

    Prices are stored as currency-specific cents (int) to preserve exact
    arithmetic. ``monthly_price_cents``/``annual_price_cents`` are the USD
    points (backward-compatible with the original catalog API); ``prices``
    holds the full per-currency table. ``None`` means custom pricing
    (Enterprise).
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
    prices: dict[str, PlanPrice] = Field(
        default_factory=dict, description="Per-currency fixed price points"
    )
    features: PlanLimits = Field(default_factory=PlanLimits)


_starters_modules = [
    "Core ERP · inventory, sales, cash, orders",
    "Market intel · 1 signal source",
    "1 AI agent",
    "Email verification & MFA",
]

_professional_modules = [
    "Full ERP suite · inventory, sales, cash, orders",
    "Market intel · all 5 signal sources",
    "5 AI agents",
    "Developer API access",
    "Email verification & MFA",
]

_business_modules = [
    "Full ERP suite · inventory, sales, cash, orders",
    "Market intel · all 5 signal sources",
    "Agent autopilot · automated actions",
    "Unlimited AI agents",
    "Advanced role-based permissions",
    "Developer API access",
    "Email verification & MFA",
]

_enterprise_modules = [
    "Full ERP suite · inventory, sales, cash, orders",
    "Market intel · all 5 signal sources",
    "Agent autopilot · automated actions",
    "Unlimited AI agents",
    "Advanced role-based permissions",
    "Developer API access",
    "SSO / SAML",
    "Custom data integrations",
    "Dedicated infrastructure",
    "Email verification & MFA",
]

#: Fixed per-currency price points, reviewed manually (SKY-40). The annual
#: figure is the monthly-equivalent when billed yearly, mirroring the USD
#: catalog (29 -> 24, 79 -> 66). Never derived from FX. The AUD/CAD/SGD
#: figures are the business-approved beta numbers (the two annual figures
#: that break the 10/12 rounding convention - AUD professional, CAD business
#: - are deliberate business choices, asserted verbatim by the unit tests).
#: Pending markets (AED/SAR) intentionally have NO rows here until pricing
#: is approved - see PRICING_PENDING_CURRENCIES.
_CURRENCY_PRICES = {
    "professional": {
        "usd": (2_900, 2_400),
        "inr": (199_900, 166_600),
        "gbp": (2_400, 2_000),
        "eur": (2_600, 2_200),
        "aud": (4_500, 3_700),
        "cad": (3_900, 3_200),
        "sgd": (3_900, 3_200),
    },
    "business": {
        "usd": (7_900, 6_600),
        "inr": (599_900, 499_900),
        "gbp": (6_600, 5_500),
        "eur": (7_200, 6_000),
        "aud": (11_900, 9_900),
        "cad": (10_500, 8_700),
        "sgd": (10_500, 8_700),
    },
}


def _price_points(
    plan_id: str, monthly_cents: int | None, annual_cents: int | None
) -> dict[str, PlanPrice]:
    """Build the per-currency price table for a catalog plan.

    Paid plans carry a fixed table for every PRICED currency; free
    (Starter) and custom-priced (Enterprise) plans carry the same entries
    so the resolution stays symmetric, with ``None``/0 amounts as
    appropriate. Pricing-pending markets (AED/SAR) get no rows at all -
    their residents are region-blocked before any price is rendered and
    their checkout is rejected server-side.
    """
    paid_table = _CURRENCY_PRICES.get(plan_id)
    table: dict[str, tuple[int | None, int | None]]
    if paid_table is not None:
        table = {
            code: (monthly_cents, annual_cents)
            for code, (monthly_cents, annual_cents) in paid_table.items()
        }
    else:
        table = dict.fromkeys(PRICED_CURRENCIES, (monthly_cents, annual_cents))
    return {
        code: PlanPrice(
            currency=code,
            monthly_cents=table[code][0],
            annual_cents=table[code][1],
            display_locale=CURRENCY_LOCALES[code],
        )
        for code in PRICED_CURRENCIES
    }


PLANS: dict[str, Plan] = {
    "starter": Plan(
        id="starter",
        tier="starter",
        display_name="Starter",
        monthly_price_cents=0,
        annual_price_cents=0,
        prices=_price_points("starter", 0, 0),
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
        prices=_price_points("professional", 2_900, 2_400),
        features=PlanLimits(
            max_users=10,
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
        prices=_price_points("business", 7_900, 6_600),
        features=PlanLimits(
            max_users=None,
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
        prices=_price_points("enterprise", None, None),
        features=PlanLimits(
            max_users=None,
            ai_credits_monthly=None,
            max_agents=None,
            modules=_enterprise_modules,
        ),
    ),
}
