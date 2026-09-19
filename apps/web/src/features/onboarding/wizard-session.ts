/**
 * Tiny sessionStorage bridge for the pre-login wizard context.
 *
 * The Stripe Checkout return URL only carries plan+interval+checkout, so the
 * Review page needs the full wizard context (email, vt, tenantId, slug) to be
 * restored client-side.  We persist it right before the Stripe redirect and
 * right before the Plan→Review transition so both paths have access.
 */

import type {
    BillingCurrency,
    BillingInterval,
    BillingPlanId,
} from "@/lib/api/billing-api";

export interface WizardSession {
    email: string;
    vt: string;
    tenantId: string;
    slug: string;
    plan: BillingPlanId;
    interval: BillingInterval;
    currency: BillingCurrency;
}

const KEY = "skyrict.onboarding.session";

export function saveWizardSession(session: WizardSession): void {
    try {
        sessionStorage.setItem(KEY, JSON.stringify(session));
    } catch {
        /* SSR or private-browsing — safe to ignore. */
    }
}

export function loadWizardSession(): Partial<WizardSession> | null {
    try {
        const raw = sessionStorage.getItem(KEY);
        if (!raw) return null;
        return JSON.parse(raw) as Partial<WizardSession>;
    } catch {
        return null;
    }
}

export function clearWizardSession(): void {
    try {
        sessionStorage.removeItem(KEY);
    } catch {
        /* noop */
    }
}
