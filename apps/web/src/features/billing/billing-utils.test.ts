import { describe, expect, it } from "vitest";

import type { BillingPlan, BillingSubscription } from "@/lib/api/billing-api";
import {
    formatPriceCents,
    isTrialActive,
    purchasablePlans,
    trialCountdownLabel,
} from "@/features/billing/billing-utils";

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
    const plans: BillingPlan[] = [
        { id: "starter", tier: "starter", display_name: "Starter", monthly_price_cents: 0, annual_price_cents: 0, features: { max_users: 1, ai_credits_monthly: 500, max_agents: 1, modules: [] } },
        { id: "professional", tier: "pro", display_name: "Professional", monthly_price_cents: 2900, annual_price_cents: 2400, features: { max_users: 5, ai_credits_monthly: 5000, max_agents: 5, modules: [] } },
        { id: "business", tier: "business", display_name: "Business", monthly_price_cents: 7900, annual_price_cents: 6600, features: { max_users: 20, ai_credits_monthly: 20000, max_agents: null, modules: [] } },
        { id: "enterprise", tier: "enterprise", display_name: "Enterprise", monthly_price_cents: null, annual_price_cents: null, features: { max_users: null, ai_credits_monthly: null, max_agents: null, modules: [] } },
    ];

    it("offers only Professional and Business through Checkout", () => {
        expect(purchasablePlans(plans).map((plan) => plan.id)).toEqual([
            "professional",
            "business",
        ]);
    });
});