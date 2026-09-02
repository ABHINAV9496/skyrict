"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getComplianceSummary, type HrComplianceSummary } from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const SEVERITY_STYLES: Record<string, string> = {
  critical: "bg-destructive/10 text-destructive ring-1 ring-destructive/30",
  high: "bg-orange-500/15 text-orange-700 ring-1 ring-orange-500/30 dark:text-orange-400",
  medium: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  low: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
};

const SEVERITY_LABEL: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const TYPE_LABEL: Record<string, string> = {
  document_expiry: "Document expiry",
  training_overdue: "Overdue training",
  contract_missing_field: "Missing record field",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", SEVERITY_STYLES[severity] ?? "bg-muted text-muted-foreground")}
    >
      {SEVERITY_LABEL[severity] ?? severity}
    </Badge>
  );
}

function SummaryCards({ summary }: { summary: HrComplianceSummary }) {
  const severities = ["critical", "high", "medium", "low"] as const;
  return (
    <section aria-label="Compliance summary" className="space-y-4">
      <div className="flex items-center gap-2">
        <Badge
          variant="outline"
          className="border-indigo-500/30 bg-indigo-500/10 text-indigo-700 dark:text-indigo-400"
        >
          L1 aggregate
        </Badge>
        <p className="text-xs text-muted-foreground">Counts only — no per-person data.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {severities.map((severity) => {
          const label = SEVERITY_LABEL[severity];
          return (
            <div key={severity} className="rounded-xl border border-border bg-card p-4">
              <p className="text-xs font-medium text-muted-foreground">{label}</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground">
                {summary.bySeverity[severity] ?? 0}
              </p>
            </div>
          );
        })}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Open findings</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground">
            {summary.openFindings}
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              of {summary.totalFindings} total
            </span>
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">By check type</p>
          <div className="mt-2 space-y-1.5">
            {Object.entries(summary.byType).length > 0 ? (
              Object.entries(summary.byType).map(([type, count]) => (
                <div key={type} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-muted-foreground">{TYPE_LABEL[type] ?? type}</span>
                  <span className="font-medium tabular-nums text-foreground">{count}</span>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">No compliance findings.</p>
            )}
          </div>
        </div>
      </div>
      {summary.narrative || summary.generatedAt ? (
        <div className="rounded-xl border border-border bg-card p-4">
          {summary.narrative ? <p className="text-sm text-muted-foreground">{summary.narrative}</p> : null}
          {summary.generatedAt ? (
            <p className="mt-2 text-xs text-muted-foreground">As of {formatDateTime(summary.generatedAt)}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function ComplianceClient() {
  const [view, setView] = useState<
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "summary"; summary: HrComplianceSummary }
  >({ state: "loading" });

  const load = useCallback(async () => {
    setView({ state: "loading" });
    try {
      const summary = await getComplianceSummary();
      setView({ state: "summary", summary });
    } catch (error) {
      setView({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load compliance findings.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const empty = view.state === "summary" && view.summary.totalFindings === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Compliance"
        description="Auto-generated compliance findings — expiring identity documents, overdue required training, and missing employee record fields."
        icon={ShieldCheck}
      />

      {view.state === "error" ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-destructive">{view.message}</p>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : null}

      {view.state === "loading" ? (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-card" />
            ))}
          </div>
          <div className="h-40 animate-pulse rounded-xl border border-border bg-card" />
        </div>
      ) : null}

      {view.state === "summary" ? (
        <>
          <SummaryCards summary={view.summary} />
          {empty ? (
            <section
              aria-label="No compliance findings"
              className="rounded-xl border border-border bg-card p-4"
            >
              <div className="flex items-center gap-2">
                <SeverityBadge severity="low" />
                <p className="text-xs text-muted-foreground">
                  No compliance findings right now — identity documents are current, training is up
                  to date, and employee records are complete.
                </p>
              </div>
            </section>
          ) : (
            <section
              aria-label="Individual drill-down locked"
              className="rounded-xl border border-border bg-card p-4"
            >
              <div className="flex items-center gap-2">
                <Badge
                  variant="outline"
                  className="border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-400"
                >
                  L2 individual
                </Badge>
                <p className="text-xs text-muted-foreground">
                  Per-employee findings are served to erp.hr.ai.individual holders against a
                  specific employee id — the aggregate feed above never exposes them.
                </p>
              </div>
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
