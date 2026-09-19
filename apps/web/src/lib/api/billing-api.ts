import { apiFetch, apiPost } from "@/lib/api/http";

const BILLING = "/api/v1/billing";

/** Plan feature limits from the server-side catalog (ADR-009, is authoritative). */
export interface BillingPlanLimits {
    max_users: number | null;
    ai_credits_monthly: number | null;
    max_agents: number | null;
    modules: string[];
}

/** Fixed price point for one currency (mirrors PlanPriceResponse). */
export interface BillingPlanPrice {
    currency: BillingCurrency;
    /** Price in cents of the currency; null means custom-priced (Enterprise). */
    monthly_cents: number | null;
    /** Annual monthly-equivalent in currency cents; null = custom. */
    annual_cents: number | null;
    /** BCP-47 locale used to render prices in this currency. */
    display_locale: string;
}

/**
 * Billing currency — the beta checkout allowlist (hardcoded, mirrors
 * SUPPORTED_CURRENCIES in services/identity .../billing/plans.py). Fixed
 * per-currency price points are reviewed manually - never derived from a
 * live FX rate. Outside this list checkout is rejected server-side.
 */
export type BillingCurrency =
    | "usd"
    | "inr"
    | "gbp"
    | "eur"
    | "aud"
    | "cad"
    | "sgd"
    | "aed"
    | "sar";

/** One catalog row - mirrors PlanResponse (GET /billing/plans). */
export interface BillingPlan {
    id: string;
    tier: string;
    display_name: string;
    /** USD cents; null means custom-priced (Enterprise). */
    monthly_price_cents: number | null;
    /** USD cents, monthly-equivalent when billed yearly; null = custom. */
    annual_price_cents: number | null;
    /** Per-currency fixed price points (keyed by lowercase currency code). */
    prices: Partial<Record<BillingCurrency, BillingPlanPrice>>;
    features: BillingPlanLimits;
}

/**
 * Billing plan id, matching the backend `PLAN_ID_LITERAL`
 * (services/identity/src/identity/features/billing/plans.py).
 */
export type BillingPlanId =
    "starter" | "professional" | "business" | "enterprise";

/** Billing interval accepted by Checkout (backend `Literal["month", "year"]`). */
export type BillingInterval = "month" | "year";

/**
 * Current workspace subscription - mirrors SubscriptionResponse
 * (GET /billing/subscription). `subscription_status` is one of
 * none | trialing | active | past_due | canceled | expired.
 */
export interface BillingSubscription {
    plan_id: string;
    plan_tier: string;
    subscription_status: string;
    trial_ends_at: string | null;
    days_remaining: number;
    billing_email: string | null;
}

/** Stripe Checkout session - redirect the browser to `url`. */
export interface CheckoutSession {
    session_id: string;
    url: string;
}

/** Stripe Customer Portal session - redirect the browser to `url`. */
export interface PortalSession {
    session_id: string;
    url: string;
}

/** Current subscription for the active workspace (any authenticated member). */
export function getBillingSubscription(): Promise<BillingSubscription> {
    return apiFetch<BillingSubscription>(`${BILLING}/subscription`);
}

/** Full plan catalog in canonical order (any authenticated member). */
export function listBillingPlans(): Promise<BillingPlan[]> {
    return apiFetch<BillingPlan[]>(`${BILLING}/plans`);
}

/**
 * Start a Stripe Checkout session for a paid plan upgrade (owner only).
 * The owner's browser is then redirected to the returned `url`. `currency`
 * selects a currency-specific Stripe Price; the server falls back to the USD
 * Price when the locale has no configured Price.
 */
export function createCheckoutSession(
    planId: BillingPlanId,
    interval: BillingInterval,
    currency: BillingCurrency = "usd",
): Promise<CheckoutSession> {
    return apiPost<CheckoutSession>(`${BILLING}/checkout-session`, {
        planId,
        interval,
        currency,
    });
}

/**
 * Open the Stripe Customer Portal to manage billing (owner only).
 * The owner's browser is then redirected to the returned `url`.
 */
export function createPortalSession(): Promise<PortalSession> {
    return apiPost<PortalSession>(`${BILLING}/portal-session`, {});
}
