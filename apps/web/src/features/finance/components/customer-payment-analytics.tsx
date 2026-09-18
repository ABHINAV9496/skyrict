"use client";

import { useCallback, useEffect, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
    getCustomerAnalytics,
    type CustomerPaymentAnalytics,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { useLatestRequest } from "@/lib/hooks/use-latest-request";
import { formatMoney } from "@/lib/finance/format";
import { cn } from "@/lib/utils";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import {
    FinanceEmptyState,
    FinanceErrorState,
} from "@/features/finance/components/state-cards";

type Entry = CustomerPaymentAnalytics["entries"][number];

function ConsistencyTag({ score }: { score: number | null }) {
    if (score === null) return <span className="text-muted-foreground">—</span>;
    const label = `${(score * 100).toFixed(1)}%`;
    return (
        <span
            className={cn(
                "inline-flex rounded-full px-2 py-0.5 text-xs font-medium",
                score >= 0.7
                    ? "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                    : score >= 0.4
                      ? "bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                      : "bg-red-500/10 text-red-700 dark:bg-red-500/15 dark:text-red-300",
            )}
        >
            {label}
        </span>
    );
}

function daysLabel(days: number | null): string {
    if (days === null) return "—";
    const rounded = Number(days.toFixed(1));
    return `${rounded} days`;
}

export function CustomerPaymentAnalytics({
    fromDate,
    toDate,
}: {
    fromDate: string;
    toDate: string;
}) {
    const [analytics, setAnalytics] = useState<CustomerPaymentAnalytics | null>(
        null,
    );
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const requestGuard = useLatestRequest();

    const load = useCallback(async () => {
        const requestId = requestGuard.next();
        setLoading(true);
        setError(null);
        try {
            const result = await getCustomerAnalytics(fromDate, toDate);
            if (!requestGuard.isCurrent(requestId)) return;
            setAnalytics(result);
        } catch (err) {
            if (!requestGuard.isCurrent(requestId)) return;
            setError(
                err instanceof ApiError
                    ? err.message
                    : "Could not load payment analytics.",
            );
        } finally {
            if (requestGuard.isCurrent(requestId)) setLoading(false);
        }
    }, [fromDate, toDate, requestGuard]);

    useEffect(() => {
        void load();
    }, [load]);

    if (loading) {
        return (
            <div className="flex items-center justify-center gap-2 rounded-xl border border-border bg-card px-6 py-12 text-sm text-muted-foreground">
                <RefreshCw aria-hidden="true" className="size-4 animate-spin" />
                Loading payment analytics…
            </div>
        );
    }

    if (error) {
        return (
            <FinanceErrorState message={error} onRetry={() => void load()} />
        );
    }

    if (!analytics || analytics.entries.length === 0) {
        return (
            <FinanceEmptyState
                icon={BarChart3}
                title="No payment analytics yet"
                description="Payments applied to invoices in this period drive the analytics view."
            />
        );
    }

    const columns: FinanceColumn<Entry>[] = [
        {
            label: "Customer",
            render: (entry) => entry.customer_name ?? entry.customer_id,
        },
        {
            label: "Payments",
            align: "right",
            render: (entry) => entry.payment_count,
        },
        {
            label: "Total paid",
            align: "right",
            render: (entry) => (
                <span className="tabular-nums">
                    {formatMoney(entry.total_paid)}
                </span>
            ),
        },
        {
            label: "Avg days to pay",
            align: "right",
            render: (entry) => daysLabel(entry.avg_days_to_pay),
        },
        {
            label: "Consistency",
            align: "right",
            render: (entry) => (
                <ConsistencyTag score={entry.consistency_score} />
            ),
        },
    ];

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">
                    How quickly each customer pays, based on applied payments
                    between {fromDate} and {toDate}.
                </p>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => void load()}
                >
                    <RefreshCw aria-hidden="true" className="size-3.5" />
                    Refresh
                </Button>
            </div>
            <FinanceTable
                columns={columns}
                rows={analytics.entries}
                getKey={(entry) => entry.customer_id}
                footer={`${analytics.entries.length} customers in the selected period`}
            />
        </div>
    );
}
