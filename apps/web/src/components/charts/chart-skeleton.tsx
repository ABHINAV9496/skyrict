"use client";

/** Fixed-height placeholder for a chart that loads after hydration. The h-72
 *  matches the chart container it replaces, so the split does not shift layout
 *  (no CLS) while the recharts chunk is fetched. */
export function ChartSkeleton() {
    return (
        <div
            aria-hidden="true"
            className="h-72 rounded-xl border border-border bg-card p-4"
        >
            <div className="h-full w-full animate-pulse rounded-lg bg-muted" />
        </div>
    );
}