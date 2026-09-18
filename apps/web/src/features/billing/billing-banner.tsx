"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";

import { getBillingSubscription } from "@/lib/api/billing-api";
import {
    isTrialActive,
    trialCountdownLabel,
} from "@/features/billing/billing-utils";

/**
 * Trial countdown banner shown to every workspace member while the tenant is
 * in its free trial. Progressive enhancement: any fetch failure hides the
 * banner rather than blocking the dashboard shell.
 */
export function BillingTrialBanner() {
    const [daysRemaining, setDaysRemaining] = useState<number | null>(null);

    const load = useCallback(() => {
        getBillingSubscription()
            .then((subscription) => {
                if (isTrialActive(subscription)) {
                    setDaysRemaining(subscription.days_remaining);
                } else {
                    setDaysRemaining(null);
                }
            })
            .catch(() => setDaysRemaining(null));
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    if (daysRemaining === null) return null;

    return (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <p className="flex items-center gap-2 text-sm text-foreground">
                <Sparkles aria-hidden="true" className="size-4 shrink-0 text-primary" />
                <span>
                    You&apos;re on a free trial - {trialCountdownLabel(daysRemaining)}.
                    Upgrade anytime to keep your workspace at full power.
                </span>
            </p>
            <Link
                href="/dashboard/settings/billing"
                className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
            >
                Choose a plan
            </Link>
        </div>
    );
}