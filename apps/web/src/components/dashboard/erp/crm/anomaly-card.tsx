"use client";

import { useState } from "react";
import { AlertTriangle, Info, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/http";
import {
    dismissCrmAnomaly,
    resolveCrmAnomaly,
    type CrmAnomalyItem,
} from "@/lib/api/crm-ai-api";
import { formatDate } from "@/lib/erp/money";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Severity + rule presentation
// ---------------------------------------------------------------------------

const SEVERITY_CONFIG: Record<
    string,
    { icon: typeof AlertTriangle; label: string; color: string }
> = {
    critical: {
        icon: AlertTriangle,
        label: "Critical",
        color: "bg-destructive/15 text-destructive ring-1 ring-destructive/30",
    },
    warning: {
        icon: AlertTriangle,
        label: "Warning",
        color: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
    },
    info: {
        icon: Info,
        label: "Info",
        color: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
    },
};

const RULE_LABELS: Record<string, string> = {
    activity_bulk: "Activity burst",
    missing_next_activity: "Missing activity",
    stage_stall: "Stage stall",
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AnomalyCardProps {
    item: CrmAnomalyItem;
    /** Called after resolve/dismiss so the parent can refresh its list. */
    onAction?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AnomalyCard({ item, onAction }: AnomalyCardProps) {
    const [busy, setBusy] = useState<"resolve" | "dismiss" | null>(null);
    const [done, setDone] = useState(false);

    const config = SEVERITY_CONFIG[item.severity] ?? SEVERITY_CONFIG.info;
    const Icon = config.icon;

    const handleAction = async (action: "resolve" | "dismiss") => {
        setBusy(action);
        try {
            if (action === "resolve") {
                await resolveCrmAnomaly(item.id);
            } else {
                await dismissCrmAnomaly(item.id);
            }
            setDone(true);
            onAction?.();
        } catch (err) {
            const msg =
                err instanceof ApiError
                    ? err.message
                    : "Could not update the anomaly.";
            // eslint-disable-next-line no-alert -- non-critical user feedback
            alert(msg);
        } finally {
            setBusy(null);
        }
    };

    if (done) {
        return (
            <div className="rounded-xl border border-border bg-muted/30 p-4 opacity-60">
                <p className="text-xs text-muted-foreground italic">Handled</p>
            </div>
        );
    }

    return (
        <div className="space-y-3 rounded-xl border border-border bg-card p-4">
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                    <Badge
                        variant="secondary"
                        className={cn("text-xs", config.color)}
                    >
                        <Icon aria-hidden="true" className="mr-1 size-3" />
                        {config.label}
                    </Badge>
                    <Badge variant="outline" className="text-[10px]">
                        {RULE_LABELS[item.rule_id] ?? item.rule_id}
                    </Badge>
                </div>
                <span className="text-[10px] text-muted-foreground tabular-nums">
                    {formatDate(item.detected_at)}
                </span>
            </div>

            {/* Finding */}
            <div>
                <p className="text-sm font-medium text-foreground">
                    {item.title}
                </p>
                <p className="mt-0.5 text-sm text-muted-foreground">
                    {item.description}
                </p>
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-1">
                <Button
                    size="sm"
                    variant="outline"
                    className="flex-1"
                    onClick={() => void handleAction("resolve")}
                    disabled={busy !== null}
                >
                    {busy === "resolve" ? (
                        <Loader2
                            aria-hidden="true"
                            className="mr-1 size-3 animate-spin"
                        />
                    ) : (
                        <AlertTriangle
                            aria-hidden="true"
                            className="mr-1 size-3"
                        />
                    )}
                    Resolve
                </Button>
                <Button
                    size="sm"
                    variant="ghost"
                    className="flex-1 text-muted-foreground"
                    onClick={() => void handleAction("dismiss")}
                    disabled={busy !== null}
                >
                    <X aria-hidden="true" className="mr-1 size-3" />
                    Dismiss
                </Button>
            </div>
        </div>
    );
}