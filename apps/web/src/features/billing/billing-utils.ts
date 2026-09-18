import type {
    BillingCurrency,
    BillingInterval,
    BillingPlan,
    BillingSubscription,
} from "@/lib/api/billing-api";
import { CURRENCY_META } from "@/lib/billing/currency";

const priceFormatters = new Map<string, Intl.NumberFormat>();

function priceFormatter(currency: BillingCurrency): Intl.NumberFormat {
    let formatter = priceFormatters.get(currency);
    if (!formatter) {
        formatter = new Intl.NumberFormat(CURRENCY_META[currency].locale, {
            style: "currency",
            currency: currency.toUpperCase(),
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
        priceFormatters.set(currency, formatter);
    }
    return formatter;
}

/**
 * Format a currency-cent price for display. Whole-unit amounts drop the
 * decimals (₹1,999 not ₹1,999.00); fractional cents keep two decimals.
 * `null` = custom, `0` = free, matching the original USD-only formatter.
 */
export function formatPriceForCurrency(
    cents: number | null,
    currency: BillingCurrency = "usd",
): string {
    if (cents === null) return "Custom";
    if (cents === 0) return "Free";
    if (cents % 100 !== 0) {
        return new Intl.NumberFormat(CURRENCY_META[currency].locale, {
            style: "currency",
            currency: currency.toUpperCase(),
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(cents / 100);
    }
    return priceFormatter(currency).format(cents / 100);
}

/** Format a USD-cent price for display; `null` = custom, `0` = free. */
export function formatPriceCents(cents: number | null): string {
    return formatPriceForCurrency(cents, "usd");
}

/** A price resolved against the catalog for a currency + interval. */
export interface ResolvedPlanPrice {
    /** Amount in cents of `currency` (null = custom-priced plan). */
    cents: number | null;
    /** Currency the amount is actually denominated in. */
    currency: BillingCurrency;
    /** True when the requested currency had no fixed point and USD was used. */
    billedInUsd: boolean;
}

/**
 * Resolve a plan's fixed price for a currency + interval (SKY-40).
 *
 * The catalog always carries every supported currency; this is defensive
 * against catalog/frontend drift: when a requested currency is missing the
 * USD price is used and ``billedInUsd`` tells the UI to show a
 * "Billed in USD" note at checkout.
 */
export function resolvePlanPrice(
    plan: BillingPlan,
    currency: BillingCurrency,
    interval: BillingInterval,
): ResolvedPlanPrice {
    const point = plan.prices[currency];
    if (point) {
        return {
            cents:
                interval === "year" ? point.annual_cents : point.monthly_cents,
            currency,
            billedInUsd: false,
        };
    }
    const usd = plan.prices.usd;
    if (usd) {
        return {
            cents: interval === "year" ? usd.annual_cents : usd.monthly_cents,
            currency: "usd",
            billedInUsd: currency !== "usd",
        };
    }
    // No currency table at all (pre-multi-currency catalog): fall back to the
    // legacy USD fields so the migration is seamless.
    return {
        cents:
            interval === "year"
                ? plan.annual_price_cents
                : plan.monthly_price_cents,
        currency: "usd",
        billedInUsd: currency !== "usd",
    };
}

/** The trial banner should render while the workspace is in its free trial. */
export function isTrialActive(subscription: BillingSubscription): boolean {
    return subscription.subscription_status === "trialing";
}

/** Human countdown for the trial banner. */
export function trialCountdownLabel(daysRemaining: number): string {
    if (daysRemaining <= 0) return "your trial ends today";
    if (daysRemaining === 1) return "your trial ends tomorrow";
    return `your trial ends in ${daysRemaining} days`;
}

/**
 * Plans the owner can purchase through Stripe Checkout: Starter is free and
 * Enterprise is custom-priced, so only Professional and Business are offered.
 */
export function purchasablePlans(plans: BillingPlan[]): BillingPlan[] {
    return plans.filter(
        (plan) => plan.id === "professional" || plan.id === "business",
    );
}

/** Human label for a subscription status from the backend. */
export function subscriptionStatusLabel(status: string): string {
    switch (status) {
        case "trialing":
            return "Trial";
        case "active":
            return "Active";
        case "past_due":
            return "Past due";
        case "canceled":
            return "Canceled";
        case "expired":
            return "Expired";
        default:
            return "Free";
    }
}
