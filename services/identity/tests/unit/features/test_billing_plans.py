"""Unit tests for the billing plan catalog and tier mapping (SKY-33 / ADR-009)."""

from __future__ import annotations

from identity.core.config import settings
from identity.features.billing.plans import (
    PLAN_ID_MAP,
    PLANS,
    TIER_MAP,
    Plan,
    resolve_plan_id,
    resolve_tier,
)


def test_plan_id_map_is_bidirectional() -> None:
    """Every frontend planId maps to a tier and back to the same planId."""
    assert len(PLAN_ID_MAP) == 4
    for plan_id, tier in PLAN_ID_MAP.items():
        assert tier in TIER_MAP
        assert TIER_MAP[tier] == plan_id


def test_professional_maps_to_pro_tier() -> None:
    """The professional planId is canonicalized to the 'pro' DB tier."""
    assert resolve_tier("professional") == "pro"
    assert resolve_plan_id("pro") == "professional"


def test_known_plan_ids_map_identically() -> None:
    assert resolve_tier("starter") == "starter"
    assert resolve_tier("business") == "business"
    assert resolve_tier("enterprise") == "enterprise"


def test_unknown_value_passes_through() -> None:
    """Unmapped inputs (e.g. a raw tier already in DB form) pass through."""
    assert resolve_tier("pro") == "pro"
    assert resolve_plan_id("professional") == "professional"


def test_catalog_exposes_all_four_plans() -> None:
    assert set(PLANS) == {"starter", "professional", "business", "enterprise"}
    for plan in PLANS.values():
        assert isinstance(plan, Plan)
        assert plan.id == plan.id
        assert plan.tier == PLAN_ID_MAP[plan.id]


def test_prices_match_frontend_catalog_in_cents() -> None:
    """Prices mirror apps/web onboarding (Starter $0, Pro $29/$24, Biz $79/$66)."""
    assert PLANS["starter"].monthly_price_cents == 0
    assert PLANS["starter"].annual_price_cents == 0
    assert PLANS["professional"].monthly_price_cents == 2_900
    assert PLANS["professional"].annual_price_cents == 2_400
    assert PLANS["business"].monthly_price_cents == 7_900
    assert PLANS["business"].annual_price_cents == 6_600
    assert PLANS["enterprise"].monthly_price_cents is None
    assert PLANS["enterprise"].annual_price_cents is None


def test_enterprise_has_custom_pricing_only() -> None:
    plan = PLANS["enterprise"]
    assert plan.monthly_price_cents is None
    assert plan.annual_price_cents is None
    assert plan.features.max_users is None
    assert plan.features.ai_credits_monthly is None


def test_feature_limits_are_typed() -> None:
    starter = PLANS["starter"].features
    pro = PLANS["professional"].features
    business = PLANS["business"].features

    assert starter.max_users == 1
    assert starter.ai_credits_monthly == 500
    assert starter.max_agents == 1

    assert pro.max_users == 5
    assert pro.ai_credits_monthly == 5_000
    assert pro.max_agents == 5

    assert business.max_users == 20
    assert business.ai_credits_monthly == 20_000
    assert business.max_agents is None


def test_module_escalation() -> None:
    """Higher tiers strictly add modules - the feature list never shrinks."""
    starter_modules = set(PLANS["starter"].features.modules)
    pro_modules = set(PLANS["professional"].features.modules)
    business_modules = set(PLANS["business"].features.modules)
    enterprise_modules = set(PLANS["enterprise"].features.modules)

    assert pro_modules - starter_modules, "Professional must add modules over Starter"
    assert business_modules - pro_modules, "Business must add modules over Professional"
    assert enterprise_modules - business_modules, "Enterprise must add modules over Business"


def test_default_currency_is_usd() -> None:
    """Catalog prices are cents; the configured currency defaults to usd."""
    assert settings.BILLING_CURRENCY == "usd"
