import { beforeEach, describe, expect, it, vi } from "vitest";

import {
    createCheckoutSession,
    createPortalSession,
    getBillingSubscription,
    listBillingPlans,
} from "@/lib/api/billing-api";
import type { apiFetchEnvelope } from "@/lib/api/http";

const httpMock = vi.fn<typeof apiFetchEnvelope>();

type Envelope = { data?: unknown; meta?: unknown };

/**
 * Simulate the real http helpers: `apiFetch` unwraps `payload.data`, matching
 * lib/api/http.ts so a regression that changes the unwrap contract is caught.
 */
vi.mock("@/lib/api/http", () => ({
    apiFetch: async (_path: string, _options: RequestInit = {}) => {
        const result = await httpMock(_path, _options);
        return (result as Envelope).data;
    },
    apiFetchEnvelope: (_path: string, _options?: RequestInit) =>
        httpMock(_path, _options),
    apiPost: async (_path: string, _body?: unknown) => {
        const result = await httpMock(_path, {
            method: "POST",
            body: JSON.stringify(_body),
        });
        return (result as Envelope).data;
    },
}));

describe("billing subscription and catalog reads", () => {
    beforeEach(() => {
        httpMock.mockReset();
    });

    it("reads the workspace subscription", async () => {
        httpMock.mockResolvedValue({
            data: {
                plan_id: "professional",
                plan_tier: "pro",
                subscription_status: "trialing",
                trial_ends_at: "2026-09-28T09:00:00Z",
                days_remaining: 10,
                billing_email: null,
            },
            meta: null,
        });

        const sub = await getBillingSubscription();

        expect(httpMock).toHaveBeenCalledWith(
            "/api/v1/billing/subscription",
            {},
        );
        expect(sub).toEqual({
            plan_id: "professional",
            plan_tier: "pro",
            subscription_status: "trialing",
            trial_ends_at: "2026-09-28T09:00:00Z",
            days_remaining: 10,
            billing_email: null,
        });
    });

    it("lists the plan catalog in canonical order", async () => {
        httpMock.mockResolvedValue({
            data: [
                {
                    id: "professional",
                    tier: "pro",
                    display_name: "Professional",
                    monthly_price_cents: 2900,
                    annual_price_cents: 2400,
                    features: {
                        max_users: 5,
                        ai_credits_monthly: 5000,
                        max_agents: 5,
                        modules: ["localytics", "finance"],
                    },
                },
            ],
            meta: null,
        });

        const plans = await listBillingPlans();

        expect(httpMock).toHaveBeenCalledWith("/api/v1/billing/plans", {});
        expect(plans[0]).toMatchObject({
            id: "professional",
            monthly_price_cents: 2900,
            annual_price_cents: 2400,
        });
    });
});

describe("billing mutations", () => {
    beforeEach(() => {
        httpMock.mockReset();
    });

    it("starts a checkout session with a camelCase body and month interval", async () => {
        httpMock.mockResolvedValue({
            data: {
                session_id: "cs_test_1",
                url: "https://checkout.stripe.com/c/pay/cs_test_1",
            },
            meta: null,
        });

        const session = await createCheckoutSession("professional", "month");

        expect(httpMock).toHaveBeenCalledWith(
            "/api/v1/billing/checkout-session",
            {
                method: "POST",
                body: JSON.stringify({ planId: "professional", interval: "month" }),
            },
        );
        expect(session.session_id).toBe("cs_test_1");
        expect(session.url).toContain("checkout.stripe.com");
    });

    it("starts a checkout session with the year interval", async () => {
        httpMock.mockResolvedValue({
            data: {
                session_id: "cs_test_2",
                url: "https://checkout.stripe.com/c/pay/cs_test_2",
            },
            meta: null,
        });

        await createCheckoutSession("professional", "year");

        expect(httpMock).toHaveBeenCalledWith(
            "/api/v1/billing/checkout-session",
            {
                method: "POST",
                body: JSON.stringify({ planId: "professional", interval: "year" }),
            },
        );
    });

    it("opens the customer portal with an empty body", async () => {
        httpMock.mockResolvedValue({
            data: {
                session_id: "ps_test_1",
                url: "https://billing.stripe.com/p/session/ps_test_1",
            },
            meta: null,
        });

        const session = await createPortalSession();

        expect(httpMock).toHaveBeenCalledWith(
            "/api/v1/billing/portal-session",
            { method: "POST", body: "{}" },
        );
        expect(session.session_id).toBe("ps_test_1");
        expect(session.url).toContain("billing.stripe.com");
    });
});