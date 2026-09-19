"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowLeftRight } from "lucide-react";

import { ChartSkeleton } from "@/components/charts/chart-skeleton";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { L3NarrativeCard } from "@/components/dashboard/erp/hr/l3-narrative-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CardSkeleton } from "@/components/ui/page-skeletons";
import { ApiError } from "@/lib/api/http";
import {
    getLeavePayCorrelation,
    type LeavePayPair,
} from "@/lib/api/hr-api";

type PageStatus =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; pairs: LeavePayPair[] };

// recharts lives in the dynamically-imported chart chunk; ssr:false keeps it
// out of this route's first-load JS and ChartSkeleton reserves the height.
const LazyCorrelationChart = dynamic(
    () =>
        import(
            "@/app/dashboard/erp/hr/correlation/leave-pay-correlation-chart"
        ).then((m) => m.LeavePayCorrelationChart),
    { ssr: false, loading: ChartSkeleton },
);

export function CorrelationClient() {
    const [status, setStatus] = useState<PageStatus>({ state: "loading" });

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const pairs = await getLeavePayCorrelation();
            setStatus({ state: "ready", pairs });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load the leave-pay series.",
            });
        }
    }, []);

    useEffect(() => {
        void load();
    }, [load]);

    const points = useMemo(
        () =>
            status.state === "ready"
                ? status.pairs.map((pair) => ({
                      name: pair.runCode,
                      leaveDays: pair.leaveDays,
                      overtime: Number(pair.overtime),
                  }))
                : [],
        [status],
    );

    return (
        <div className="space-y-6">
            <PageHeader
                title="Leave · pay correlation"
                description="How monthly approved-leave days track against overtime paid — the data behind the L3 correlation narrative."
                icon={ArrowLeftRight}
            />

            {status.state === "error" ? (
                <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-10 text-center">
                    <p className="text-sm font-medium text-destructive">{status.message}</p>
                    <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => void load()}
                    >
                        Try again
                    </Button>
                </div>
            ) : null}

            {status.state === "loading" ? (
                <div className="space-y-4">
                    <CardSkeleton className="h-80" />
                    <CardSkeleton className="h-48" />
                </div>
            ) : null}

            {status.state === "ready" ? (
                <>
                    <section
                        aria-label="Leave days vs overtime"
                        className="rounded-xl border border-border bg-card p-5"
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                                Monthly observations
                            </h2>
                            <Badge variant="outline" className="capitalize">
                                {status.pairs.length >= 12
                                    ? `${status.pairs.length} months of paired data`
                                    : `${status.pairs.length} months — thin data, correlation may abstain`}
                            </Badge>
                        </div>
                        <p className="text-xs text-muted-foreground">
                            Each point is one payroll run: approved leave days (x) against
                            overtime paid (y).
                        </p>
                        {points.length > 0 ? (
                            <LazyCorrelationChart points={points} />
                        ) : (
                            <p className="mt-3 text-sm text-muted-foreground">
                                No paired leave-pay observations yet.
                            </p>
                        )}
                    </section>

                    <L3NarrativeCard
                        kind="leave_pay_correlation"
                        accessibilityLabel="Leave and pay correlation narrative"
                    />
                </>
            ) : null}
        </div>
    );
}