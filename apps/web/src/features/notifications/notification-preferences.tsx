"use client";

import { useCallback, useEffect, useState } from "react";
import { BellRing, Lock, Mail, Webhook } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
    listNotificationPreferences,
    updateNotificationPreference,
    type NotificationPreference,
} from "@/lib/api/notifications-api";
import { cn } from "@/lib/utils";

type Channel = "in_app_on" | "email_on" | "webhook_on";

const CHANNELS: { key: Channel; label: string; icon: typeof BellRing }[] = [
    { key: "in_app_on", label: "In-app", icon: BellRing },
    { key: "email_on", label: "Email", icon: Mail },
    { key: "webhook_on", label: "Webhook", icon: Webhook },
];

/**
 * Per-category notification preferences (SKY-93). Every authenticated user may
 * read and update their own preferences; mandatory categories (e.g.
 * compliance) keep the in-app channel forced on - the backend rejects any
 * attempt to disable it, so the UI disables that toggle.
 */
export function NotificationPreferences() {
    const [preferences, setPreferences] = useState<NotificationPreference[] | null>(null);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [savingCategory, setSavingCategory] = useState<string | null>(null);

    const load = useCallback(() => {
        listNotificationPreferences()
            .then(setPreferences)
            .catch(() => setPreferences([]));
    }, []);

    useEffect(() => {
        load();
    }, [load]);

    async function toggleChannel(
        category: string,
        channel: Channel,
        current: NotificationPreference,
    ) {
        if (current.mandatory && channel === "in_app_on") return;
        const next = {
            in_app_on:
                channel === "in_app_on"
                    ? !current.in_app_on
                    : current.in_app_on || current.mandatory,
            email_on:
                channel === "email_on" ? !current.email_on : current.email_on,
            webhook_on:
                channel === "webhook_on"
                    ? !current.webhook_on
                    : current.webhook_on,
        };
        setSavingCategory(category);
        setSaveError(null);
        try {
            const updated = await updateNotificationPreference(category, next);
            setPreferences((currentList) =>
                currentList?.map((pref) =>
                    pref.category === category ? updated : pref,
                ) ?? currentList,
            );
        } catch (error) {
            setSaveError(
                error instanceof Error
                    ? error.message
                    : "Could not save your preferences.",
            );
        } finally {
            setSavingCategory(null);
        }
    }

    return (
        <div className="space-y-6 pb-8">
            <PageHeader
                title="Notification preferences"
                description="Choose which channels receive each category of notification."
                icon={BellRing}
            />

            {saveError && (
                <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                    {saveError}
                </div>
            )}

            <section className="rounded-xl border border-border bg-card">
                <div className="flex items-center justify-between border-b border-border px-4 py-3">
                    <h2 className="text-sm font-semibold text-foreground">
                        Categories
                    </h2>
                    <span className="text-xs text-muted-foreground">
                        Channels apply to all recipients of the category
                    </span>
                </div>

                {preferences === null ? (
                    <div className="divide-y divide-border">
                        {Array.from({ length: 4 }).map((_, index) => (
                            <div key={index} className="flex items-center gap-3 px-4 py-3">
                                <Skeleton className="h-4 w-1/4 rounded" />
                                <Skeleton className="h-6 w-1/3 rounded-full" />
                            </div>
                        ))}
                    </div>
                ) : preferences.length === 0 ? (
                    <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                        No notification categories are configured yet.
                    </div>
                ) : (
                    <ul className="divide-y divide-border">
                        {preferences.map((pref) => (
                            <li
                                key={pref.category}
                                className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
                            >
                                <div className="min-w-0">
                                    <p className="truncate text-sm font-medium text-foreground">
                                        {pref.label}
                                    </p>
                                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                                        {pref.mandatory
                                            ? "Required - cannot be turned off"
                                            : "You receive this only when it applies to you"}
                                    </p>
                                </div>
                                <div
                                    className="flex flex-wrap items-center gap-2"
                                    role="group"
                                    aria-label={`${pref.label} channels`}
                                >
                                    {pref.mandatory && (
                                        <Lock
                                            aria-hidden="true"
                                            className="mr-1 size-4 text-muted-foreground/50"
                                        />
                                    )}
                                    {CHANNELS.map(({ key, label, icon: Icon }) => {
                                        const enabled = pref[key];
                                        const locked =
                                            pref.mandatory && key === "in_app_on";
                                        return (
                                            <Button
                                                key={key}
                                                type="button"
                                                variant={enabled ? "default" : "outline"}
                                                size="sm"
                                                disabled={
                                                    locked ||
                                                    savingCategory === pref.category
                                                }
                                                aria-pressed={enabled}
                                                onClick={() =>
                                                    void toggleChannel(
                                                        pref.category,
                                                        key,
                                                        pref,
                                                    )
                                                }
                                                className={cn(
                                                    enabled &&
                                                        !locked &&
                                                        "border-primary/40 bg-primary/10 text-primary hover:bg-primary/15",
                                                )}
                                            >
                                                <Icon aria-hidden="true" className="size-3.5" />
                                                {label}
                                            </Button>
                                        );
                                    })}
                                </div>
                            </li>
                        ))}
                    </ul>
                )}
            </section>
        </div>
    );
}