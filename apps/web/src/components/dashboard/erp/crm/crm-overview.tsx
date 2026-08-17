"use client";

import { useCallback, useEffect, useState, type ComponentType } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clock,
  Contact,
  LayoutDashboard,
  Plus,
  Target,
  TrendingUp,
  Trophy,
  Users,
  ArrowRight,
} from "lucide-react";

import { ErrorState } from "@/components/dashboard/erp/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getCrmOverview,
  listRecentTimeline,
  listCustomers,
  type CrmOverview,
  type Customer,
  type MoneyBucket,
  type Opportunity,
  type TimelineItem,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import {
  ENTITY_TYPE_LABELS,
  OPPORTUNITY_STAGE_LABELS,
  opportunityStageBadgeClass,
  timelineEventLabel,
} from "@/lib/erp/labels";
import { formatDate, formatMoney, formatPercent } from "@/lib/erp/money";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      overview: CrmOverview;
      timeline: TimelineItem[];
      customerList: Customer[];
    };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ACTIVE_STAGES = ["prospecting", "qualified", "proposal", "negotiation"] as const;

const STAGE_BAR: Record<string, string> = {
  prospecting: "bg-sky-500 dark:bg-sky-400",
  qualified: "bg-violet-500 dark:bg-violet-400",
  proposal: "bg-amber-500 dark:bg-amber-400",
  negotiation: "bg-primary",
};

const STAGE_DOT: Record<string, string> = {
  prospecting: "bg-sky-500",
  qualified: "bg-violet-500",
  proposal: "bg-amber-500",
  negotiation: "bg-primary",
};

const TIMELINE_SOURCE_ICON: Record<string, ComponentType<{ className?: string }>> = {
  activity: Clock,
  note: Contact,
  event: Target,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function multiCurrency(buckets: MoneyBucket[]): string {
  if (buckets.length === 0) return "—";
  return buckets.map((b) => formatMoney(b.amount, b.currency)).join("  ");
}

function currencyBreakdown(buckets: MoneyBucket[]): string {
  if (buckets.length === 0) return "";
  return buckets
    .map((b) => `${b.currency.toUpperCase()} ${formatMoney(b.amount, b.currency)}`)
    .join("  ·  ");
}

function stageMaxCount(
  byStage: { stage: string; count: number }[],
  stages: readonly string[],
): number {
  return Math.max(1, ...stages.map((s) => byStage.find((b) => b.stage === s)?.count ?? 0));
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return formatDate(iso);
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function DashboardSkeleton() {
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[100px] rounded-lg" />
        ))}
      </div>
      <div className="grid gap-5 lg:grid-cols-5">
        <Skeleton className="h-[280px] rounded-xl lg:col-span-3" />
        <Skeleton className="h-[280px] rounded-lg lg:col-span-2" />
      </div>
      <div className="grid gap-5 lg:grid-cols-3">
        <Skeleton className="h-[200px] rounded-lg lg:col-span-2" />
        <Skeleton className="h-[200px] rounded-lg" />
      </div>
      <div className="grid gap-5 lg:grid-cols-3">
        <Skeleton className="h-[100px] rounded-lg" />
        <Skeleton className="h-[200px] rounded-lg lg:col-span-2" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function InlineEmpty({
  icon: Icon,
  message,
  actionLabel,
  actionHref,
}: {
  icon: ComponentType<{ className?: string }>;
  message: string;
  actionLabel?: string;
  actionHref?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <Icon className="mb-2 size-7 text-muted-foreground/40" />
      <p className="text-xs text-muted-foreground">{message}</p>
      {actionLabel && actionHref ? (
        <Link
          href={actionHref}
          className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
        >
          <Plus className="size-3" />
          {actionLabel}
        </Link>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section header — no bottom border, lighter weight
// ---------------------------------------------------------------------------

function SectionHeader({
  title,
  href,
  viewLabel = "View all",
}: {
  title: string;
  href: string;
  viewLabel?: string;
}) {
  return (
    <div className="flex items-center justify-between px-4 pt-3.5 pb-1">
      <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
        {title}
      </h2>
      <Link
        href={href}
        className="inline-flex items-center gap-1 text-[11px] font-medium text-primary hover:underline"
      >
        {viewLabel}
        <ArrowRight className="size-3" />
      </Link>
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
      const [overview, timelineRes, customerRes] = await Promise.all([
        getCrmOverview(),
        listRecentTimeline({ limit: 8 }),
        listCustomers({ limit: 5 }),
      ]);
      setStatus({
        state: "ready",
        overview,
        timeline: timelineRes.data,
        customerList: customerRes.data,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load the CRM overview.";
      setStatus({ state: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const overview = status.state === "ready" ? status.overview : null;

  const maxCount = overview
    ? stageMaxCount(overview.opportunities.byStage, ACTIVE_STAGES)
    : 1;

  if (status.state === "loading") return <DashboardSkeleton />;
  if (status.state === "error")
    return <ErrorState message={status.message} onRetry={() => void load()} />;

  const { leads, opportunities, customers, activities, topOpportunities, recentWon } =
    status.overview;
  const timeline = status.timeline;
  const customerList = status.customerList;

  return (
    <div className="space-y-5">
      {/* ================================================================ */}
      {/* ROW 1 — KPI summary                                              */}
      {/* ================================================================ */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {/* Open Pipeline */}
        <Link
          href="/dashboard/erp/crm/opportunities"
          className="group rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/30 hover:bg-primary/[0.02]"
        >
          <div className="flex items-start gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <TrendingUp className="size-4 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Open pipeline
              </p>
              <p className="mt-0.5 font-display text-xl font-bold tracking-tight text-foreground tabular-nums">
                {multiCurrency(opportunities.openValue)}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {opportunities.openCount} open deal
                {opportunities.openCount !== 1 ? "s" : ""}
              </p>
            </div>
          </div>
          {opportunities.openValue.length > 0 && (
            <div className="mt-2.5 border-t border-border/50 pt-2">
              <p className="mb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                By currency
              </p>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                {opportunities.openValue.map((b) => (
                  <span
                    key={b.currency}
                    className="text-[11px] tabular-nums text-muted-foreground"
                  >
                    {b.currency.toUpperCase()}{" "}
                    {formatMoney(b.amount, b.currency)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </Link>

        {/* Active Leads */}
        <div className="rounded-lg border border-border bg-card p-3">
          <div className="flex items-start gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <Contact className="size-4 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Active leads
              </p>
              <p className="mt-0.5 font-display text-xl font-bold tracking-tight text-foreground tabular-nums">
                {leads.total}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {leads.byStatus.find((s) => s.status === "new")?.count ?? 0}{" "}
                new
              </p>
            </div>
          </div>
        </div>

        {/* Won Business */}
        <div className="rounded-lg border border-border bg-card p-3">
          <div className="flex items-start gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <Trophy className="size-4 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Won business
              </p>
              <p className="mt-0.5 font-display text-xl font-bold tracking-tight text-foreground tabular-nums">
                {multiCurrency(opportunities.wonValue)}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {opportunities.wonCount} deal
                {opportunities.wonCount !== 1 ? "s" : ""} won
                {opportunities.winRate !== null
                  ? ` · ${formatPercent(opportunities.winRate)} win rate`
                  : ""}
              </p>
            </div>
          </div>
        </div>

        {/* Customers */}
        <Link
          href="/dashboard/erp/crm/customers"
          className="group rounded-lg border border-border bg-card p-3 transition-colors hover:border-primary/30 hover:bg-primary/[0.02]"
        >
          <div className="flex items-start gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10">
              <Users className="size-4 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Customers
              </p>
              <p className="mt-0.5 font-display text-xl font-bold tracking-tight text-foreground tabular-nums">
                {customers.active}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {customers.total} total
              </p>
            </div>
            {customers.total > 0 && (
              <CustomerDonut
                active={customers.active}
                total={customers.total}
              />
            )}
          </div>
        </Link>
      </section>

      {/* ================================================================ */}
      {/* ROW 2 — Pipeline hero + Follow-ups                               */}
      {/* ================================================================ */}
      <section className="grid gap-5 lg:grid-cols-5">
        {/* Pipeline by stage — hero element */}
        <div className="rounded-xl border border-primary/15 bg-card lg:col-span-3">
          <SectionHeader
            title="Pipeline"
            href="/dashboard/erp/crm/opportunities"
          />

          <div className="px-4 pb-4">
            {/* Stage bars */}
            <div className="space-y-3">
              {ACTIVE_STAGES.map((stage) => {
                const bucket = opportunities.byStage.find((b) => b.stage === stage);
                const count = bucket?.count ?? 0;
                const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                return (
                  <div key={stage}>
                    <div className="mb-1 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span
                          className={cn("size-2 rounded-full", STAGE_DOT[stage])}
                        />
                        <span className="text-xs font-medium text-foreground">
                          {OPPORTUNITY_STAGE_LABELS[stage]}
                        </span>
                      </div>
                      <span className="text-[11px] tabular-nums text-muted-foreground">
                        {count} {count === 1 ? "deal" : "deals"}
                        {bucket?.value && bucket.value.length > 0
                          ? `  · ${multiCurrency(bucket.value)}`
                          : ""}
                      </span>
                    </div>
                    <div className="h-2.5 overflow-hidden rounded-full bg-muted/50">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all duration-500",
                          STAGE_BAR[stage],
                        )}
                        style={{
                          width: `${Math.max(pct, count > 0 ? 6 : 0)}%`,
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Won / Lost summary */}
            <div className="mt-4 flex items-center gap-4 border-t border-border/50 pt-3">
              <div className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-emerald-500" />
                <span className="text-xs font-semibold tabular-nums text-foreground">
                  {opportunities.wonCount}
                </span>
                <span className="text-[11px] text-muted-foreground">won</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="size-2 rounded-full bg-red-500" />
                <span className="text-xs font-semibold tabular-nums text-foreground">
                  {opportunities.lostCount}
                </span>
                <span className="text-[11px] text-muted-foreground">lost</span>
              </div>
              {opportunities.winRate !== null && (
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {formatPercent(opportunities.winRate)} win rate
                </span>
              )}
            </div>

            {/* Multi-currency breakdown */}
            {opportunities.openValue.length > 0 && (
              <p className="mt-2.5 text-[11px] text-muted-foreground">
                {currencyBreakdown(opportunities.openValue)}
              </p>
            )}
          </div>
        </div>

        {/* Follow-up attention */}
        <div className="rounded-lg border border-border bg-card lg:col-span-2">
          <SectionHeader
            title="Follow-ups"
            href="/dashboard/erp/crm/activities"
          />

          <div className="p-4">
            {/* 2×2 stat grid */}
            <div className="grid grid-cols-2 gap-3">
              <div
                className={cn(
                  "rounded-md border p-3",
                  activities.overdue > 0
                    ? "border-red-500/25 bg-red-500/5"
                    : "border-border/60 bg-muted/20",
                )}
              >
                <p
                  className={cn(
                    "font-display text-2xl font-bold tabular-nums",
                    activities.overdue > 0
                      ? "text-red-600 dark:text-red-400"
                      : "text-foreground",
                  )}
                >
                  {activities.overdue}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Overdue
                </p>
              </div>
              <div
                className={cn(
                  "rounded-md border p-3",
                  activities.today > 0
                    ? "border-amber-500/25 bg-amber-500/5"
                    : "border-border/60 bg-muted/20",
                )}
              >
                <p
                  className={cn(
                    "font-display text-2xl font-bold tabular-nums",
                    activities.today > 0
                      ? "text-amber-600 dark:text-amber-400"
                      : "text-foreground",
                  )}
                >
                  {activities.today}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Today
                </p>
              </div>
              <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                <p className="font-display text-2xl font-bold tabular-nums text-foreground">
                  {activities.upcoming}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Upcoming
                </p>
              </div>
              <div className="rounded-md border border-border/60 bg-muted/20 p-3">
                <p className="font-display text-2xl font-bold tabular-nums text-foreground">
                  {activities.completed30d}
                </p>
                <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Done (30d)
                </p>
              </div>
            </div>

            {/* Status line */}
            <div
              className={cn(
                "mt-3 flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-semibold",
                activities.overdue > 0
                  ? "bg-red-500/5 text-red-600 dark:bg-red-500/10 dark:text-red-400"
                  : activities.today > 0
                    ? "bg-amber-500/5 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400"
                    : "bg-emerald-500/5 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400",
              )}
            >
              {activities.overdue > 0 ? (
                <AlertTriangle className="size-3" />
              ) : activities.today > 0 ? (
                <CalendarClock className="size-3" />
              ) : (
                <CheckCircle2 className="size-3" />
              )}
              {activities.overdue > 0
                ? `${activities.overdue} overdue`
                : activities.today > 0
                  ? `${activities.today} due today`
                  : "All clear"}
            </div>
          </div>
        </div>
      </section>

      {/* ================================================================ */}
      {/* ROW 3 — Top opportunities + Recent wins (independent cards)      */}
      {/* ================================================================ */}
      <div className="grid gap-5 lg:grid-cols-3">
        {/* Top opportunities — 2 cols */}
        <div className="rounded-lg border border-border bg-card lg:col-span-2">
          <SectionHeader
            title="Top opportunities"
            href="/dashboard/erp/crm/opportunities"
          />
          <div className="px-4 pb-4">
            {topOpportunities.length === 0 ? (
              <InlineEmpty
                icon={Target}
                message="No open opportunities yet"
                actionLabel="Create opportunity"
                actionHref="/dashboard/erp/crm/opportunities"
              />
            ) : (
              <ul className="divide-y divide-border/30">
                {topOpportunities.map((opp) => (
                  <OpportunityRow key={opp.id} opp={opp} />
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Recent wins — 1 col */}
        <div className="rounded-lg border border-border bg-card">
          <SectionHeader
            title="Recent wins"
            href="/dashboard/erp/crm/opportunities"
          />
          <div className="px-4 pb-4">
            {recentWon.length === 0 ? (
              <InlineEmpty
                icon={CheckCircle2}
                message="No won deals yet"
                actionLabel="View pipeline"
                actionHref="/dashboard/erp/crm/opportunities"
              />
            ) : (
              <ul className="divide-y divide-border/30">
                {recentWon.map((opp) => (
                  <WonRow key={opp.id} opp={opp} />
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      {/* ================================================================ */}
      {/* ROW 4 — Customers + Recent activity (independent cards)          */}
      {/* ================================================================ */}
      <div className="grid gap-5 lg:grid-cols-3">
        {/* Customers — 1 col */}
        <div className="rounded-lg border border-border bg-card">
          <SectionHeader
            title="Customers"
            href="/dashboard/erp/crm/customers"
          />
          <div className="px-4 pb-4">
            <div className="flex items-center gap-6">
              <div>
                <p className="font-display text-2xl font-bold tabular-nums text-primary">
                  {customers.active}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Active
                </p>
              </div>
              <div>
                <p className="font-display text-2xl font-bold tabular-nums text-foreground">
                  {customers.total}
                </p>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Total
                </p>
              </div>
            </div>
            {customerList.length > 0 && (
              <ul className="mt-3 divide-y divide-border/30">
                {customerList.map((c) => (
                  <li key={c.id}>
                    <Link
                      href={`/dashboard/erp/crm/customers/${c.id}`}
                      className="group flex items-center justify-between gap-2 py-2 transition-colors hover:bg-muted/20 -mx-1 px-1 rounded"
                    >
                      <span className="truncate text-xs font-medium text-foreground group-hover:text-primary">
                        {c.name}
                      </span>
                      {c.email && (
                        <span className="shrink-0 text-[10px] text-muted-foreground truncate max-w-[80px]">
                          {c.email}
                        </span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {customers.total === 0 && (
              <p className="mt-3 text-[11px] text-muted-foreground">
                No customers yet — win a deal to create one.
              </p>
            )}
          </div>
        </div>

        {/* Recent activity — 2 cols */}
        <div className="rounded-lg border border-border bg-card lg:col-span-2">
          <SectionHeader
            title="Recent activity"
            href="/dashboard/erp/crm/activities"
          />
          <div className="px-4 pb-4">
            {timeline.length === 0 ? (
              <InlineEmpty
                icon={Clock}
                message="No recent activity"
                actionLabel="Log activity"
                actionHref="/dashboard/erp/crm/activities"
              />
            ) : (
              <ul className="space-y-0.5">
                {timeline.map((item) => (
                  <ActivityRow
                    key={`${item.source}-${item.id}`}
                    item={item}
                  />
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      {/* Footer */}
      <p className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <LayoutDashboard className="size-3" />
        Overview reflects your current workspace scope.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function OpportunityRow({ opp }: { opp: Opportunity }) {
  return (
    <li>
      <Link
        href={`/dashboard/erp/crm/opportunities/${opp.id}`}
        className="group flex items-center gap-3 py-2.5 transition-colors hover:bg-muted/20 -mx-1 px-1 rounded"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground group-hover:text-primary">
            {opp.name || "Unnamed"}
          </p>
          <div className="mt-0.5 flex items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ring-1 ring-inset",
                opportunityStageBadgeClass(opp.stage),
              )}
            >
              {OPPORTUNITY_STAGE_LABELS[opp.stage]}
            </span>
            <span className="text-[10px] tabular-nums text-muted-foreground">
              {opp.probability}%
            </span>
            {opp.expectedCloseDate && (
              <span className="text-[10px] text-muted-foreground">
                {formatDate(opp.expectedCloseDate)}
              </span>
            )}
          </div>
        </div>
        <span className="shrink-0 w-[90px] text-right font-display text-sm font-semibold tabular-nums text-foreground">
          {formatMoney(opp.amount, opp.currency)}
        </span>
      </Link>
    </li>
  );
}

function WonRow({ opp }: { opp: Opportunity }) {
  return (
    <li>
      <Link
        href={`/dashboard/erp/crm/opportunities/${opp.id}`}
        className="group flex items-center gap-3 py-2.5 transition-colors hover:bg-muted/20 -mx-1 px-1 rounded"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-foreground group-hover:text-primary">
            {opp.name || "Unnamed"}
          </p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Won {formatDate(opp.wonAt)}
          </p>
        </div>
        <span className="shrink-0 w-[90px] text-right font-display text-sm font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
          {formatMoney(opp.amount, opp.currency)}
        </span>
      </Link>
    </li>
  );
}

function ActivityRow({ item }: { item: TimelineItem }) {
  const Icon = TIMELINE_SOURCE_ICON[item.source] ?? Clock;
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <div className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded bg-muted">
        <Icon className="size-3 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-medium text-foreground leading-tight">
          {item.title ?? timelineEventLabel(item.kind)}
        </p>
        <p className="mt-0.5 text-[10px] text-muted-foreground truncate">
          {ENTITY_TYPE_LABELS[item.entityType] ?? item.entityType}
        </p>
      </div>
      <span className="shrink-0 text-[10px] text-muted-foreground whitespace-nowrap">
        {relativeTime(item.occurredAt)}
      </span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Customer donut (small SVG ring for KPI card)
// ---------------------------------------------------------------------------

function CustomerDonut({
  active,
  total,
}: {
  active: number;
  total: number;
}) {
  const r = 13;
  const circumference = 2 * Math.PI * r;
  const pct = total > 0 ? active / total : 0;
  const offset = circumference * (1 - pct);

  return (
    <div className="relative flex size-9 shrink-0 items-center justify-center">
      <svg width="36" height="36" viewBox="0 0 36 36" className="-rotate-90">
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          className="stroke-muted"
          strokeWidth="3"
        />
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          className="stroke-primary"
          strokeWidth="3"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <span className="absolute text-[8px] font-bold tabular-nums text-foreground">
        {Math.round(pct * 100)}
      </span>
    </div>
  );
}
