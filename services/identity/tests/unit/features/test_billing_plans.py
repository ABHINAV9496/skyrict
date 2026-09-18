"""Unit tests for the billing plan catalog and tier mapping (SKY-33 / ADR-009)."""

from __future__ import annotations

from identity.core.config import settings
from identity.features.billing.plans import (
    CURRENCY_LOCALES,
    PLAN_ID_MAP,
    PLANS,
    PRICED_CURRENCIES,
    PRICING_PENDING_CURRENCIES,
    SUPPORTED_CURRENCIES,
    TIER_MAP,
    Plan,
    resolve_currency,
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

    assert pro.max_users == 10
    assert pro.ai_credits_monthly == 5_000
    assert pro.max_agents == 5

    assert business.max_users is None
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


def test_every_plan_prices_all_priced_currencies() -> None:
    """Every catalog entry carries a fixed price point per PRICED currency.

    Pricing-pending markets (AED/SAR) intentionally have no rows: their
    residents are region-blocked before any price renders and their checkout
    is rejected server-side, so a missing row can never surface as a wrong
    price.
    """
    for plan in PLANS.values():
        assert set(plan.prices) == set(PRICED_CURRENCIES)
        for code, price in plan.prices.items():
            assert price.currency == code
            assert price.display_locale == CURRENCY_LOCALES[code]
            # A paid plan's per-currency USD point mirrors the top-level field.
            if code == "usd":
                assert price.monthly_cents == plan.monthly_price_cents
                assert price.annual_cents == plan.annual_price_cents


def test_pricing_pending_currencies_are_well_formed() -> None:
    """Pending codes are allowlisted but carry no price rows in any plan."""
    assert set(PRICING_PENDING_CURRENCIES) <= set(SUPPORTED_CURRENCIES)
    assert not set(PRICED_CURRENCIES) & set(PRICING_PENDING_CURRENCIES)
    assert set(PRICED_CURRENCIES) | set(PRICING_PENDING_CURRENCIES) == set(
        SUPPORTED_CURRENCIES
    )
    for plan in PLANS.values():
        for code in PRICING_PENDING_CURRENCIES:
            assert code not in plan.prices


def test_beta_allowlist_is_exactly_the_nine_markets() -> None:
    """Guard against accidental allowlist drift (beta scope contract)."""
    assert SUPPORTED_CURRENCIES == (
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


def test_paid_plans_have_complete_price_coverage() -> None:
    """CI guard: fails if a purchasable plan has a hole in priced coverage.

    A missing/null point for a PRICED currency would silently ship a market
    we claim to support with no purchasable price for it.
    """
    for plan_id in ("professional", "business"):
        for code in PRICED_CURRENCIES:
            price = PLANS[plan_id].prices[code]
            assert price.monthly_cents is not None, (
                f"{plan_id} is missing a monthly price for {code}"
            )
            assert price.annual_cents is not None, (
                f"{plan_id} is missing an annual price for {code}"
            )
            assert price.monthly_cents > 0
            assert price.annual_cents > 0


def test_usd_price_points_match_frontend_catalog() -> None:
    assert PLANS["professional"].prices["usd"].monthly_cents == 2_900
    assert PLANS["professional"].prices["usd"].annual_cents == 2_400
    assert PLANS["business"].prices["usd"].monthly_cents == 7_900
    assert PLANS["business"].prices["usd"].annual_cents == 6_600


def test_inr_fixed_price_points_use_lakh_grouping_locale() -> None:
    """Indian fixed points and the en-IN locale (renders ₹1,99,900)."""
    pro = PLANS["professional"].prices["inr"]
    assert pro.monthly_cents == 199_900
    assert pro.annual_cents == 166_600
    assert pro.display_locale == "en-IN"
    biz = PLANS["business"].prices["inr"]
    assert biz.monthly_cents == 599_900
    assert biz.annual_cents == 499_900


def test_gbp_and_eur_fixed_price_points() -> None:
    assert PLANS["professional"].prices["gbp"].monthly_cents == 2_400
    assert PLANS["professional"].prices["gbp"].annual_cents == 2_000
    assert PLANS["professional"].prices["eur"].monthly_cents == 2_600
    assert PLANS["professional"].prices["eur"].annual_cents == 2_200


def test_free_and_custom_plans_are_unpriced_in_every_priced_currency() -> None:
    """Starter is 0 and Enterprise is custom (None) in all priced currencies."""
    for code in PRICED_CURRENCIES:
        assert PLANS["starter"].prices[code].monthly_cents == 0
        assert PLANS["starter"].prices[code].annual_cents == 0
        assert PLANS["enterprise"].prices[code].monthly_cents is None
        assert PLANS["enterprise"].prices[code].annual_cents is None


def test_annual_is_ten_of_twelve_monthly_in_convention_currencies() -> None:
    """The original markets keep the 10/12 annual-equivalent convention.

    Newer beta markets (AUD/CAD/SGD) use business-approved annual figures
    asserted verbatim below; two of them round differently than 10/12 on
    purpose (AUD professional $37, CAD business $87).
    """
    for plan_id in ("professional", "business"):
        for code in ("usd", "inr", "gbp", "eur"):
            price = PLANS[plan_id].prices[code]
            if price.monthly_cents is None:
                continue
            expected = round(price.monthly_cents * 10 / 12 / 100) * 100
            assert price.annual_cents == expected


def test_aud_cad_sgd_fixed_price_points_match_business() -> None:
    """Business-approved beta price points, asserted verbatim (not FX-derived)."""
    pro = PLANS["professional"].prices
    assert pro["aud"].monthly_cents == 4_500
    assert pro["aud"].annual_cents == 3_700
    assert pro["aud"].display_locale == "en-AU"
    assert pro["cad"].monthly_cents == 3_900
    assert pro["cad"].annual_cents == 3_200
    assert pro["cad"].display_locale == "en-CA"
    assert pro["sgd"].monthly_cents == 3_900
    assert pro["sgd"].annual_cents == 3_200
    assert pro["sgd"].display_locale == "en-SG"
    biz = PLANS["business"].prices
    assert biz["aud"].monthly_cents == 11_900
    assert biz["aud"].annual_cents == 9_900
    assert biz["cad"].monthly_cents == 10_500
    assert biz["cad"].annual_cents == 8_700
    assert biz["sgd"].monthly_cents == 10_500
    assert biz["sgd"].annual_cents == 8_700


def test_resolve_currency_normalizes_and_rejects() -> None:
    assert resolve_currency("USD") == "usd"
    assert resolve_currency(" inr ") == "inr"
    assert resolve_currency("aud") == "aud"
    assert resolve_currency("AED") == "aed"
    assert resolve_currency("jpy") is None
    assert resolve_currency("brl") is None
    assert resolve_currency("") is None
