"use client";

import { useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";

import { StatCardSkeleton } from "@/components/ui/page-skeletons";
import type { Kpi } from "@/lib/mock/erp";
import { cn } from "@/lib/utils";

export function ErpReportsKpis() {
  const [kpis, setKpis] = useState<Kpi[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/erp/reports")
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("failed"))))
      .then((body) => {
        if (!cancelled) setKpis((body.data as { kpis: Kpi[] }).kpis);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
        <AlertCircle aria-hidden="true" className="size-4 shrink-0 text-destructive" />
        Couldn&apos;t load report data.
      </div>
    );
  }

  if (!kpis) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCardSkeleton />
        <StatCardSkeleton />
        <StatCardSkeleton />
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {kpis.map((kpi) => (
        <div key={kpi.label} className="rounded-xl border border-border bg-card p-5">
          <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
            {kpi.label}
          </p>
          <p className="mt-2 font-display text-2xl font-semibold tracking-tight text-foreground">
            {kpi.value}
          </p>
          <p
            className={cn(
              "mt-1 text-sm font-medium",
              kpi.positive
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-600 dark:text-red-400",
            )}
          >
            {kpi.delta}
          </p>
        </div>
      ))}
    </div>
  );
}
