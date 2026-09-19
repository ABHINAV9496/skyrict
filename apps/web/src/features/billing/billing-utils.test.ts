import { describe, expect, it } from "vitest";

import type {
    BillingCurrency,
    BillingPlan,
    BillingSubscription,
} from "@/lib/api/billing-api";
import {
    formatPriceCents,
    formatPriceForCurrency,
    isTrialActive,
    purchasablePlans,
    resolvePlanPrice,
    subscriptionStatusLabel,
    trialCountdownLabel,
} from "@/features/billing/billing-utils";

function price(
    currency: BillingCurrency,
    monthlyCents: number | null,
    annualCents: number | null,
) {
    return {
        currency,
        monthly_cents: monthlyCents,
        annual_cents: annualCents,
        display_locale:
            currency === "inr"
                ? "en-IN"
                : currency === "gbp"
                  ? "en-GB"
                  : currency === "eur"
                    ? "de-DE"
                    : "en-US",
    };
}

function plan(id: BillingPlan["id"]): BillingPlan {
    const monthly =
        id === "starter"
            ? 0
            : id === "professional"
              ? 2900
              : id === "business"
                ? 7900
                : null;
    const annual =
        id === "starter"
            ? 0
            : id === "professional"
              ? 2400
              : id === "business"
                ? 6600
                : null;
    return {
        id,
        tier: id,
        display_name: id.charAt(0).toUpperCase() + id.slice(1),
        monthly_price_cents: monthly,
        annual_price_cents: annual,
        prices: {
            usd: price("usd", monthly, annual),
            inr: price(
                "inr",
                annual === null || monthly === null ? annual : monthly * 6.8,
                annual,
            ),
        },
        features: {
            max_users:
                id === "starter"
                    ? 1
                    : id === "professional"
                      ? 5
                      : id === "business"
                        ? 20
                        : null,
            ai_credits_monthly:
                id === "starter"
                    ? 500
                    : id === "professional"
                      ? 5000
                      : id === "business"
                        ? 20000
                        : null,
            max_agents:
                id === "starter"
                    ? 1
                    : id === "professional"
                      ? 5
                      : id === "business"
                        ? null
                        : null,
            modules: [],
        },
    };
}

const PLANS: BillingPlan[] = [
    plan("starter"),
    plan("professional"),
    plan("business"),
    plan("enterprise"),
];

describe("formatPriceCents", () => {
    it("renders whole-dollar cents without decimals", () => {
        expect(formatPriceCents(2900)).toBe("$29");
        expect(formatPriceCents(2400)).toBe("$24");
    });

    it("renders fractional cents with two decimals", () => {
        expect(formatPriceCents(2950)).toBe("$29.50");
    });

    it("renders free and custom plans", () => {
        expect(formatPriceCents(0)).toBe("Free");
        expect(formatPriceCents(null)).toBe("Custom");
    });
});

describe("formatPriceForCurrency", () => {
    it("keeps USD rendering identical to formatPriceCents", () => {
        expect(formatPriceForCurrency(2900, "usd")).toBe("$29");
        expect(formatPriceForCurrency(2950, "usd")).toBe("$29.50");
        expect(formatPriceForCurrency(0, "usd")).toBe("Free");
        expect(formatPriceForCurrency(null, "usd")).toBe("Custom");
    });

    it("formats INR with Indian (lakh) grouping via the en-IN locale", () => {
        expect(formatPriceForCurrency(199900, "inr")).toBe("₹1,999");
        expect(formatPriceForCurrency(123456700, "inr")).toBe("₹12,34,567");
    });

    it("formats GBP and EUR with their symbols", () => {
        expect(formatPriceForCurrency(2400, "gbp")).toBe("£24");
        // de-DE renders the symbol after the amount (with a non-breaking
        // space) by convention.
        expect(formatPriceForCurrency(2600, "eur")).toBe(`26\u00A0€`);
    });

    it("renders fractional cents with two decimals in any currency", () => {
        expect(formatPriceForCurrency(2450, "gbp")).toBe("£24.50");
    });
});

describe("resolvePlanPrice", () => {
    it("uses the per-currency price point when present", () => {
        const pro = PLANS.find((p) => p.id === "professional") as BillingPlan;
        const monthly = resolvePlanPrice(pro, "inr", "month");
        expect(monthly.cents).toBe(2900 * 6.8);
        expect(monthly.currency).toBe("inr");
        expect(monthly.billedInUsd).toBe(false);
    });

    it("falls back to the USD price with billedInUsd=true when unset", () => {
        const pro = PLANS.find((p) => p.id === "professional") as BillingPlan;
        // The fixture pins an INR annual point (2400), so exercise the fallback
        // with a currency that has no prices table entry.
        const gbp = resolvePlanPrice(pro, "gbp", "month");
        expect(gbp.cents).toBe(2900);
        expect(gbp.currency).toBe("usd");
        expect(gbp.billedInUsd).toBe(true);
    });

    it("keeps free and custom plans unpriced in every currency", () => {
        const starter = PLANS.find((p) => p.id === "starter") as BillingPlan;
        const enterprise = PLANS.find(
            (p) => p.id === "enterprise",
        ) as BillingPlan;
        expect(resolvePlanPrice(starter, "inr", "month").cents).toBe(0);
        expect(resolvePlanPrice(enterprise, "inr", "month").cents).toBe(null);
        expect(resolvePlanPrice(enterprise, "gbp", "year").cents).toBe(null);
    });
});

describe("isTrialActive", () => {
    function sub(status: string): BillingSubscription {
        return {
            plan_id: "professional",
            plan_tier: "pro",
            subscription_status: status,
            trial_ends_at: "2026-09-28T09:00:00Z",
            days_remaining: 3,
            billing_email: null,
        };
    }

    it("is true only while trialing", () => {
        expect(isTrialActive(sub("trialing"))).toBe(true);
        expect(isTrialActive(sub("active"))).toBe(false);
        expect(isTrialActive(sub("expired"))).toBe(false);
        expect(isTrialActive(sub("past_due"))).toBe(false);
        expect(isTrialActive(sub("none"))).toBe(false);
    });
});

describe("trialCountdownLabel", () => {
    it("handles today, tomorrow, and multi-day countdowns", () => {
        expect(trialCountdownLabel(0)).toBe("your trial ends today");
        expect(trialCountdownLabel(1)).toBe("your trial ends tomorrow");
        expect(trialCountdownLabel(14)).toBe("your trial ends in 14 days");
    });
});

describe("purchasablePlans", () => {
    const plans: BillingPlan[] = PLANS;

    it("offers only Professional and Business through Checkout", () => {
        expect(purchasablePlans(plans).map((plan) => plan.id)).toEqual([
            "professional",
            "business",
        ]);
    });
});

describe("subscriptionStatusLabel", () => {
    it("labels every backend status", () => {
        expect(subscriptionStatusLabel("trialing")).toBe("Trial");
        expect(subscriptionStatusLabel("active")).toBe("Active");
        expect(subscriptionStatusLabel("past_due")).toBe("Past due");
        expect(subscriptionStatusLabel("canceled")).toBe("Canceled");
        expect(subscriptionStatusLabel("expired")).toBe("Expired");
        expect(subscriptionStatusLabel("none")).toBe("Free");
        expect(subscriptionStatusLabel("anything-else")).toBe("Free");
    });
});
