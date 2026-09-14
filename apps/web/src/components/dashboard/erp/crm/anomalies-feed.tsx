"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, ShieldAlert } from "lucide-react";

import { AnomalyCard } from "@/components/dashboard/erp/crm/anomaly-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/http";
import {
    listCrmAnomalies,
    type CrmAnomalyItem,
} from "@/lib/api/crm-ai-api";

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; items: CrmAnomalyItem[] };

/**
 * Open CRM pipeline anomaly inbox - the hourly scan's findings, newest first.
 * Rendered inside the CRM AI Insights page; resolving/dismissing an anomaly
 * refreshes the feed so terminal rows disappear.
 */
export function AnomaliesFeed() {
    const [status, setStatus] = useState<Status>({ state: "loading" });

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const items = await listCrmAnomalies();
            setStatus({ state: "ready", items });
        } catch (err) {
            const msg =
                err instanceof ApiError
                    ? err.message
                    : "Could not load anomalies.";
            setStatus({ state: "error", message: msg });
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    if (status.state === "loading") {
        return (
            <div className="flex items-center justify-center py-12">
                <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    if (status.state === "error") {
        return (
            <p className="py-8 text-center text-sm text-destructive">
                {status.message}
            </p>
        );
    }

    const { items } = status;

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <h2 className="flex items-center gap-2 font-display text-lg font-semibold tracking-tight text-foreground">
                    <ShieldAlert
                        aria-hidden="true"
                        className="size-5 text-primary"
                    />
                    Pipeline anomalies
                    {items.length > 0 ? (
                        <Badge
                            variant="destructive"
                            className="text-[10px]"
                        >
                            {items.length}
                        </Badge>
                    ) : null}
                </h2>
                <Button variant="outline" size="sm" onClick={() => void load()}>
                    <RefreshCw aria-hidden="true" className="mr-1.5 size-4" />
                    Refresh
                </Button>
            </div>
            {items.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">
                    No open pipeline anomalies - every tracked deal looks
                    healthy.
                </p>
            ) : (
                <div className="space-y-3">
                    {items.map((item) => (
                        <AnomalyCard
                            key={item.id}
                            item={item}
                            onAction={() => void load()}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}