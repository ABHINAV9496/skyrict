import type { BillingPlan, BillingSubscription } from "@/lib/api/billing-api";

/** Format a USD-cent price for display; `null` = custom, `0` = free. */
export function formatPriceCents(cents: number | null): string {
    if (cents === null) return "Custom";
    if (cents === 0) return "Free";
    const whole = cents / 100;
    return `$${whole % 1 === 0 ? whole.toFixed(0) : whole.toFixed(2)}`;
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
    return plans.filter((plan) => plan.id === "professional" || plan.id === "business");
}