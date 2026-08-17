"use client";

import { useCallback, useEffect, useState, type ComponentType } from "react";
import Link from "next/link";
import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Contact,
  LayoutDashboard,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";

import { ErrorState } from "@/components/dashboard/erp/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { getCrmOverview, type CrmOverview, type MoneyBucket } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { OPPORTUNITY_STAGE_LABELS, opportunityStageBadgeClass } from "@/lib/erp/labels";
import { formatMoney, formatPercent, formatDate } from "@/lib/erp/money";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; overview: CrmOverview };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FUNNEL_STAGES = ["prospecting", "qualified", "proposal", "negotiation"] as const;

const STAGE_BAR_COLORS: Record<string, string> = {
  prospecting: "bg-primary/25",
  qualified: "bg-sky-500/35",
  proposal: "bg-violet-500/35",
  negotiation: "bg-amber-500/35",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function bucketValue(buckets: MoneyBucket[]): string {
  if (buckets.length === 0) return "—";
  return buckets.map((b) => formatMoney(b.amount, b.currency)).join(" · ");
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KpiTile({
  icon: Icon,
  label,
  value,
  hint,
  accent,
}: {
  icon: ComponentType<{ "aria-hidden"?: boolean; className?: string }>;
  label: string;
  value: string;
  hint?: string;
  accent?: "emerald" | "sky" | "default";
}) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <Icon aria-hidden className="size-4 text-muted-foreground" />
        <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
          {label}
        </p>
      </div>
      <p className="mt-2 font-display text-2xl font-semibold tracking-tight text-foreground tabular-nums">
        {value}
      </p>
      {hint ? (
        <p
          className={cn(
            "mt-1 font-display text-xs font-semibold tracking-tight",
            accent === "emerald"
              ? "text-emerald-600 dark:text-emerald-400"
              : accent === "sky"
                ? "text-sky-600 dark:text-sky-400"
                : "text-muted-foreground",
          )}
        >
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function OverviewLoadingSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-4">
        <Skeleton className="h-36 rounded-2xl lg:col-span-2" />
        <Skeleton className="h-36 rounded-xl" />
        <Skeleton className="h-36 rounded-xl" />
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Skeleton className="h-80 rounded-xl lg:col-span-2" />
        <Skeleton className="h-80 rounded-xl" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-72 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
      <Skeleton className="h-24 rounded-xl" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CrmOverview() {
  const [status, setStatus] = useState<Status>({ state: "loading" });

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const overview = await getCrmOverview();
      setStatus({ state: "ready", overview });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load the CRM overview.";
      setStatus({ state: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") return <OverviewLoadingSkeleton />;
  if (status.state === "error") return <ErrorState message={status.message} onRetry={() => void load()} />;

  const { overview } = status;
  const { leads, opportunities, customers, activities } = overview;

  const maxFunnelCount = Math.max(
    1,
    ...FUNNEL_STAGES.map((s) => opportunities.byStage.find((b) => b.stage === s)?.count ?? 0),
  );

  return (
    <div className="space-y-6">
      {/* --------------------------------------------------------------- */}
      {/* Hero KPI strip                                                   */}
      {/* --------------------------------------------------------------- */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {/* Pipeline value — gradient accent card */}
        <div className="relative overflow-hidden rounded-xl border border-primary/20 bg-gradient-to-br from-primary/10 via-primary/5 to-transparent p-4">
          <div className="absolute -right-4 -top-4 size-20 rounded-full bg-primary/10 blur-2xl" />
          <div className="relative">
            <div className="flex items-center gap-1.5">
              <div className="flex size-6 items-center justify-center rounded-md bg-primary/15">
                <TrendingUp aria-hidden className="size-3.5 text-primary" />
              </div>
              <p className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">
                Pipeline
              </p>
            </div>
            <p className="mt-2 font-display text-2xl font-bold tracking-tight text-foreground">
              {bucketValue(opportunities.openValue)}
            </p>
            <div className="mt-1.5 flex items-center gap-2">
              <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                {opportunities.openCount} open
              </span>
              <span className="text-xs text-muted-foreground">deals</span>
            </div>
          </div>
        </div>

        <KpiTile icon={Contact} label="Leads" value={String(leads.total)} />
        <KpiTile
          icon={Target}
          label="Won"
          value={String(opportunities.wonCount)}
          hint={opportunities.winRate !== null ? `${formatPercent(opportunities.winRate)} win rate` : undefined}
          accent="emerald"
        />
        <KpiTile
          icon={Users}
          label="Customers"
          value={String(customers.active)}
          hint={`${customers.total} total`}
          accent="sky"
        />
      </section>

      {/* --------------------------------------------------------------- */}
      {/* Pipeline funnel + activity pulse                                 */}
      {/* --------------------------------------------------------------- */}
      <section className="grid gap-6 lg:grid-cols-3">
        {/* Pipeline funnel */}
        <div className="rounded-xl border border-border bg-card lg:col-span-2">
          <div className="flex items-center justify-between border-b border-border/60 px-5 py-3.5">
            <h2 className="flex items-center gap-2 font-display text-sm font-semibold text-foreground">
              <TrendingUp aria-hidden className="size-4 text-primary" />
              Pipeline
            </h2>
            <Link
              href="/dashboard/erp/crm/opportunities"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              View all
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </div>

          <div className="p-5">
            <div className="space-y-3">
              {FUNNEL_STAGES.map((stage, index) => {
                const bucket = opportunities.byStage.find((b) => b.stage === stage);
                const count = bucket?.count ?? 0;
                const width = maxFunnelCount > 0 ? (count / maxFunnelCount) * 100 : 0;
                return (
                  <div key={stage} className="group">
                    <div className="mb-1.5 flex items-center justify-between">
                      <div className="flex items-center gap-2.5">
                        <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-muted text-[10px] font-semibold text-muted-foreground">
                          {index + 1}
                        </span>
                        <span className="text-sm font-medium text-foreground">
                          {OPPORTUNITY_STAGE_LABELS[stage]}
                        </span>
                      </div>
                      <span className="text-sm tabular-nums text-muted-foreground">
                        {count} {count === 1 ? "deal" : "deals"}
                        {bucket?.value && bucket.value.length > 0 ? (
                          <> · {bucketValue(bucket.value)}</>
                        ) : null}
                      </span>
                    </div>
                    <div className="ml-[18px] border-l-2 border-border/50 pl-3">
                      <div className="h-7 overflow-hidden rounded-lg bg-muted/40">
                        <div
                          className={cn(
                            "h-full rounded-lg transition-all duration-700 ease-out",
                            STAGE_BAR_COLORS[stage],
                          )}
                          style={{ width: `${Math.max(width, count > 0 ? 8 : 0)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Won / lost summary */}
            <div className="mt-5 flex flex-wrap items-center gap-4 rounded-lg bg-muted/30 px-4 py-3 sm:gap-6">
              <div className="flex items-center gap-2">
                <div className="size-3 rounded-full bg-emerald-500 ring-2 ring-emerald-500/20" />
                <span className="font-display text-sm font-semibold tabular-nums text-foreground">
                  {opportunities.wonCount}
                </span>
                <span className="text-sm text-muted-foreground">won</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="size-3 rounded-full bg-red-500 ring-2 ring-red-500/20" />
                <span className="font-display text-sm font-semibold tabular-nums text-foreground">
                  {opportunities.lostCount}
                </span>
                <span className="text-sm text-muted-foreground">lost</span>
              </div>
              {opportunities.winRate !== null && (
                <span className="ml-auto hidden text-sm font-medium text-muted-foreground sm:inline">
                  {formatPercent(opportunities.winRate)} win rate
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Activity pulse */}
        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border/60 px-5 py-3.5">
            <h2 className="flex items-center gap-2 font-display text-sm font-semibold text-foreground">
              <CalendarClock aria-hidden className="size-4 text-primary" />
              Follow-ups
            </h2>
            <Link
              href="/dashboard/erp/crm/activities"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              View all
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </div>

          <div className="p-5">
            {/* Stat rows with inline bars */}
            <div className="space-y-3">
              {[
                {
                  label: "Overdue",
                  value: activities.overdue,
                  tone: "danger" as const,
                  total: Math.max(1, activities.overdue + activities.today + activities.upcoming + activities.completed30d),
                },
                {
                  label: "Today",
                  value: activities.today,
                  tone: "warning" as const,
                  total: Math.max(1, activities.overdue + activities.today + activities.upcoming + activities.completed30d),
                },
                {
                  label: "Upcoming",
                  value: activities.upcoming,
                  tone: "default" as const,
                  total: Math.max(1, activities.overdue + activities.today + activities.upcoming + activities.completed30d),
                },
                {
                  label: "Done (30d)",
                  value: activities.completed30d,
                  tone: "muted" as const,
                  total: Math.max(1, activities.completed30d),
                },
              ].map((stat) => {
                const pct = stat.total > 0 ? (stat.value / stat.total) * 100 : 0;
                return (
                  <div key={stat.label}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-display text-sm font-semibold tracking-tight text-foreground">{stat.label}</span>
                      <span className="font-display text-sm font-semibold tracking-tight tabular-nums text-foreground">{stat.value}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted/50">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all duration-500",
                          stat.tone === "danger"
                            ? "bg-red-500"
                            : stat.tone === "warning"
                              ? "bg-amber-500"
                              : stat.tone === "muted"
                                ? "bg-muted-foreground/40"
                                : "bg-primary",
                        )}
                        style={{ width: `${Math.max(pct, stat.value > 0 ? 6 : 0)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Status banner */}
            <div
              className={cn(
                "mt-4 rounded-lg px-3 py-2.5 font-display text-sm font-semibold tracking-tight",
                activities.overdue > 0
                  ? "border border-red-500/20 bg-red-500/5 text-red-600 dark:text-red-400"
                  : activities.today > 0
                    ? "border border-amber-500/20 bg-amber-500/5 text-amber-600 dark:text-amber-400"
                    : "border border-emerald-500/20 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400",
              )}
            >
              {activities.overdue > 0
                ? `${activities.overdue} overdue follow-up${activities.overdue !== 1 ? "s" : ""} needs attention`
                : activities.today > 0
                  ? `${activities.today} follow-up${activities.today !== 1 ? "s" : ""} scheduled today`
                  : "All caught up"}
            </div>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- */}
      {/* Top deals + recent wins                                          */}
      {/* --------------------------------------------------------------- */}
      <section className="grid gap-6 lg:grid-cols-2">
        {/* Top opportunities */}
        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
            <h2 className="flex items-center gap-2 font-display text-sm font-semibold text-foreground">
              <Target aria-hidden className="size-4 text-primary" />
              Top opportunities
            </h2>
            <Link
              href="/dashboard/erp/crm/opportunities"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              View all
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </div>
          <div className="p-4">
            {overview.topOpportunities.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No open opportunities in the pipeline yet.
              </p>
            ) : (
              <ul className="space-y-3">
                {overview.topOpportunities.map((opp) => (
                  <li key={opp.id}>
                    <Link
                      href={`/dashboard/erp/crm/opportunities/${opp.id}`}
                      className="group flex items-start justify-between gap-3 rounded-lg p-2 -mx-2 transition-colors hover:bg-muted/50"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground group-hover:text-primary">
                          {opp.name || "Unnamed opportunity"}
                        </p>
                        <div className="mt-1 flex items-center gap-2">
                          <span
                            className={cn(
                              "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset",
                              opportunityStageBadgeClass(opp.stage),
                            )}
                          >
                            {OPPORTUNITY_STAGE_LABELS[opp.stage]}
                          </span>
                          <span className="text-xs tabular-nums text-muted-foreground">
                            {opp.probability}%
                          </span>
                        </div>
                      </div>
                      <span className="shrink-0 font-display text-sm font-semibold tabular-nums text-foreground">
                        {formatMoney(opp.amount, opp.currency)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Recent wins */}
        <div className="rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
            <h2 className="flex items-center gap-2 font-display text-sm font-semibold text-foreground">
              <CheckCircle2 aria-hidden className="size-4 text-emerald-500" />
              Recent wins
            </h2>
            <Link
              href="/dashboard/erp/crm/opportunities"
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              View all
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </div>
          <div className="p-4">
            {overview.recentWon.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No won deals yet. Close a deal and it lands here.
              </p>
            ) : (
              <ul className="space-y-3">
                {overview.recentWon.map((opp) => (
                  <li key={opp.id}>
                    <Link
                      href={`/dashboard/erp/crm/opportunities/${opp.id}`}
                      className="group flex items-start justify-between gap-3 rounded-lg bg-emerald-500/5 p-2 -mx-2 transition-colors hover:bg-emerald-500/10 dark:bg-emerald-500/[0.03] dark:hover:bg-emerald-500/[0.06]"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium text-foreground group-hover:text-emerald-600 dark:group-hover:text-emerald-400">
                          {opp.name || "Unnamed opportunity"}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          Won {formatDate(opp.wonAt)}
                        </p>
                      </div>
                      <span className="shrink-0 font-display text-sm font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                        {formatMoney(opp.amount, opp.currency)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      {/* --------------------------------------------------------------- */}
      {/* Customer health                                                  */}
      {/* --------------------------------------------------------------- */}
      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Users aria-hidden className="size-5" />
            </div>
            <div>
              <p className="font-display text-lg font-semibold tabular-nums text-foreground">
                {customers.active} active
              </p>
              <p className="font-display text-sm font-semibold tracking-tight text-muted-foreground">
                of {customers.total} total customer{customers.total !== 1 ? "s" : ""}
                {customers.total === 0 ? " — add your first customer to get started" : ""}
              </p>
            </div>
          </div>
          <Link
            href="/dashboard/erp/crm/customers"
            className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            View all
            <ArrowRight aria-hidden className="size-3.5" />
          </Link>
        </div>
      </section>

      {/* Footer note */}
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <LayoutDashboard aria-hidden className="size-3.5" />
        Overview reflects everything you can see in your workspace scope.
      </p>
    </div>
  );
}
