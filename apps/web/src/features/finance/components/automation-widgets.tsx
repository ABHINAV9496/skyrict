"use client";

import { useCallback, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  CircleCheck,
  CircleX,
  LineChart as LineChartIcon,
  LoaderCircle,
  ScanSearch,
  Sparkles,
  SquarePen,
  TriangleAlert,
  Wand2,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/http";
import { ACCOUNT_TYPE_LABELS, formatDate, formatMoney, toMoney } from "@/lib/finance/format";
import { cn } from "@/lib/utils";
import {
  suggestAccountCode,
  type Account,
  type AccountCodeSuggestion,
  type ArAging,
  type CashflowProjection,
  type CloseChecklist,
  type ComparativePnlRow,
  type DuplicateGroup,
  type FinanceAnomaly,
  type HealthScore,
  type WorkingCapitalAlert,
} from "@/lib/api/finance-api";
import { FinanceErrorState, FinanceEmptyState } from "@/features/finance/components/state-cards";

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

export function WidgetCard({
  title,
  icon,
  hint,
  action,
  children,
}: {
  title: string;
  icon: ReactNode;
  hint?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {icon}
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-display font-semibold text-foreground">{title}</h3>
            {hint ? <p className="truncate text-xs text-muted-foreground">{hint}</p> : null}
          </div>
        </div>
        {action}
      </div>
      <div className="px-4 py-4">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Working capital
// ---------------------------------------------------------------------------

export function WorkingCapitalCard({ alert }: { alert: WorkingCapitalAlert }) {
  const ratio = toMoney(alert.ratio);
  const healthy = !alert.alert;
  return (
    <WidgetCard
      title="Working capital"
      icon={<TriangleAlert aria-hidden="true" className="size-4" />}
      hint="Current ratio · as of today"
      action={
        <span
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
            healthy
              ? "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
              : "bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
          )}
        >
          {healthy ? "Healthy" : "Alert"}
        </span>
      }
    >
      <p className="font-display text-3xl font-semibold tracking-tight text-foreground">
        {formatMoney(ratio)}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">Threshold {formatMoney(alert.threshold)}</p>
      <div className="mt-3 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">Current assets</p>
          <p className="mt-0.5 text-sm font-medium tabular-nums text-foreground">
            {formatMoney(alert.current_assets)}
          </p>
        </div>
        <div className="rounded-lg bg-muted/50 p-3">
          <p className="text-xs text-muted-foreground">Current liabilities</p>
          <p className="mt-0.5 text-sm font-medium tabular-nums text-foreground">
            {formatMoney(alert.current_liabilities)}
          </p>
        </div>
      </div>
    </WidgetCard>
  );
}

// ---------------------------------------------------------------------------
// Health score
// ---------------------------------------------------------------------------

export function HealthScoreCard({ score }: { score: HealthScore }) {
  const overall = toMoney(score.overall);
  const tone = overall >= 70 ? "success" : overall >= 40 ? "warning" : "danger";
  return (
    <WidgetCard
      title="Financial health"
      icon={<Sparkles aria-hidden="true" className="size-4" />}
      hint="Weighted score out of 100"
      action={
        <span
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
            tone === "success" &&
              "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
            tone === "warning" &&
              "bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
            tone === "danger" &&
              "bg-red-500/10 text-red-700 dark:bg-red-500/15 dark:text-red-300",
          )}
        >
          {Math.round(overall)}
        </span>
      }
    >
      <div className="space-y-3">
        {score.components.map((component) => (
          <div key={component.name}>
            <div className="mb-1 flex items-center justify-between text-sm">
              <span className="font-medium text-foreground">{component.name}</span>
              <span className="tabular-nums text-muted-foreground">
                {Math.round(toMoney(component.score))}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full",
                  toMoney(component.score) >= 70
                    ? "bg-emerald-500"
                    : toMoney(component.score) >= 40
                      ? "bg-amber-500"
                      : "bg-red-500",
                )}
                style={{ width: `${Math.max(Math.min(toMoney(component.score), 100), 2)}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </WidgetCard>
  );
}

// ---------------------------------------------------------------------------
// Cashflow projection
// ---------------------------------------------------------------------------

export function CashflowWidget({ projection }: { projection: CashflowProjection }) {
  const positions = projection.positions ?? [];
  return (
    <WidgetCard
      title="Cash-flow projection"
      icon={<LineChartIcon aria-hidden="true" className="size-4" />}
      hint={`${positions.length} months ahead`}
    >
      {positions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No projection available.</p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground uppercase">
              <tr>
                <th className="px-3 py-2 font-semibold">Month</th>
                <th className="px-3 py-2 text-right font-semibold">Opening</th>
                <th className="px-3 py-2 text-right font-semibold">Inflows</th>
                <th className="px-3 py-2 text-right font-semibold">Outflows</th>
                <th className="px-3 py-2 text-right font-semibold">Closing</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={position.month} className="border-t border-border/60">
                  <td className="px-3 py-1.5 font-medium text-foreground">{position.month}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {formatMoney(position.opening)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-emerald-600 dark:text-emerald-400">
                    {formatMoney(position.inflows)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-red-600 dark:text-red-400">
                    {formatMoney(position.outflows)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-medium tabular-nums text-foreground">
                    {formatMoney(position.closing)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </WidgetCard>
  );
}

// ---------------------------------------------------------------------------
// Anomalies
// ---------------------------------------------------------------------------

const severityTone: Record<string, "muted" | "warning" | "danger"> = {
  low: "muted",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

export function AnomalyFeed({
  anomalies,
  onScan,
  scanning,
}: {
  anomalies: FinanceAnomaly[];
  onScan: () => void;
  scanning: boolean;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-lg font-semibold tracking-tight text-foreground">
          Anomalies
        </h3>
        <Button type="button" variant="outline" size="sm" disabled={scanning} onClick={onScan}>
          {scanning ? (
            <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
          ) : (
            <ScanSearch aria-hidden="true" className="size-3.5" />
          )}
          Scan
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Detected duplicate journal entries and other unusual postings.
      </p>
      {anomalies.length === 0 ? (
        <FinanceEmptyState
          icon={ScanSearch}
          title="No anomalies"
          description="Run a scan to look for duplicate or unusual entries."
        />
      ) : (
        <div className="space-y-2">
          {anomalies.map((anomaly) => (
            <div key={anomaly.id} className="rounded-lg border border-border bg-card p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-foreground">{anomaly.anomaly_type}</span>
                <span
                  className={cn(
                    "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                    severityTone[anomaly.severity] === "danger" &&
                      "bg-red-500/10 text-red-700 dark:bg-red-500/15 dark:text-red-300",
                    severityTone[anomaly.severity] === "warning" &&
                      "bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
                    severityTone[anomaly.severity] === "muted" &&
                      "bg-muted text-muted-foreground",
                  )}
                >
                  {anomaly.severity}
                </span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{anomaly.description}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {formatDate(anomaly.detected_at.slice(0, 10))} · {anomaly.entity_type}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Duplicates
// ---------------------------------------------------------------------------

export function DuplicatesWidget({
  groups,
  loading,
  error,
  onRetry,
}: {
  groups: DuplicateGroup[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-lg font-semibold tracking-tight text-foreground">
          Potential duplicates
        </h3>
      </div>
      {loading ? (
        <div className="flex h-16 items-center justify-center text-sm text-muted-foreground">
          Checking for duplicates…
        </div>
      ) : error ? (
        <FinanceErrorState message={error} onRetry={onRetry} />
      ) : groups.length === 0 ? (
        <FinanceEmptyState
          icon={CircleCheck}
          title="No duplicates found"
          description="No similar journal entries were detected."
        />
      ) : (
        <div className="space-y-3">
          {groups.map((group) => (
            <div key={group.key} className="rounded-lg border border-border bg-card p-3">
              <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
                {group.reason}
              </p>
              <ul className="mt-2 space-y-1">
                {group.entries.map((entry) => (
                  <li
                    key={entry.entry_id}
                    className="flex items-center justify-between gap-3 text-sm"
                  >
                    <span className="truncate text-muted-foreground">
                      {entry.memo ?? "No memo"}
                    </span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {formatDate(entry.entry_date)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Close checklist
// ---------------------------------------------------------------------------

export function CloseChecklistWidget({
  list,
  loading,
}: {
  list: CloseChecklist | null;
  loading: boolean;
}) {
  return (
    <WidgetCard
      title="Close checklist"
      icon={<CircleCheck aria-hidden="true" className="size-4" />}
      hint={list ? list.period_name : undefined}
      action={
        list ? (
          <span
            className={cn(
              "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
              list.ready
                ? "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                : "bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
            )}
          >
            {list.ready ? "Ready to close" : "Open items"}
          </span>
        ) : null
      }
    >
      {loading ? (
        <div className="flex h-12 items-center justify-center text-sm text-muted-foreground">
          Loading checklist…
        </div>
      ) : list && list.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">No checklist items for this period.</p>
      ) : (
        <ul className="space-y-2">
          {list?.items.map((item) => (
            <li key={item.label} className="flex items-start gap-2.5 text-sm">
              {item.status === "pass" ? (
                <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-emerald-500" />
              ) : (
                <CircleX aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-red-500" />
              )}
              <span>
                <span className="font-medium text-foreground">{item.label}</span>
                {item.detail ? (
                  <span className="mt-0.5 block text-xs text-muted-foreground">{item.detail}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </WidgetCard>
  );
}

// ---------------------------------------------------------------------------
// Comparative P&L
// ---------------------------------------------------------------------------

export function ComparativePnlWidget({
  rows,
  caption,
  loading,
  error,
  onRetry,
}: {
  rows: ComparativePnlRow[];
  caption: string;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-display text-lg font-semibold tracking-tight text-foreground">
            Comparative profit &amp; loss
          </h3>
          <p className="text-xs text-muted-foreground">{caption}</p>
        </div>
      </div>
      {loading ? (
        <div className="flex h-16 items-center justify-center text-sm text-muted-foreground">
          Building comparison…
        </div>
      ) : error ? (
        <FinanceErrorState message={error} onRetry={onRetry} />
      ) : rows.length === 0 ? (
        <FinanceEmptyState
          icon={LineChartIcon}
          title="No comparison data"
          description="No revenue or expenses in the selected periods."
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground uppercase">
              <tr>
                <th className="px-3 py-2 font-semibold">Account</th>
                <th className="px-3 py-2 text-right font-semibold">Current</th>
                <th className="px-3 py-2 text-right font-semibold">Prior</th>
                <th className="px-3 py-2 text-right font-semibold">Variance</th>
                <th className="px-3 py-2 text-right font-semibold">%</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.account_code} className="border-t border-border/60">
                  <td className="px-3 py-1.5">
                    <code className="font-mono text-xs">{row.account_code}</code>
                    <span className="ml-2 text-foreground">{row.account_name}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {formatMoney(row.current_amount)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {formatMoney(row.prior_amount)}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 text-right tabular-nums",
                      toMoney(row.variance) < 0
                        ? "text-red-600 dark:text-red-400"
                        : "text-emerald-600 dark:text-emerald-400",
                    )}
                  >
                    {formatMoney(row.variance)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-muted-foreground">
                    {formatMoney(row.variance_pct)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AR aging
// ---------------------------------------------------------------------------

export function ArAgingWidget({
  aging,
  loading,
}: {
  aging: ArAging | null;
  loading: boolean;
}) {
  return (
    <WidgetCard
      title="AR aging"
      icon={<TriangleAlert aria-hidden="true" className="size-4" />}
      hint={aging ? `As of ${formatDate(aging.as_of)} · ${formatMoney(aging.total_ar)}` : undefined}
    >
      {loading ? (
        <div className="flex h-12 items-center justify-center text-sm text-muted-foreground">
          Loading aging…
        </div>
      ) : !aging ? (
        <p className="text-sm text-muted-foreground">No aged receivables data.</p>
      ) : (
        <div className="space-y-2">
          {aging.buckets.map((bucket) => (
            <div key={bucket.bucket}>
              <div className="mb-1 flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{bucket.bucket}</span>
                <span className="tabular-nums text-foreground">
                  {formatMoney(bucket.amount)}{" "}
                  <span className="text-xs text-muted-foreground">· {bucket.count}</span>
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full",
                    bucket.bucket.toLowerCase().includes("90") ||
                      bucket.bucket.toLowerCase().includes("120")
                      ? "bg-red-500"
                      : bucket.bucket.toLowerCase().includes("60")
                        ? "bg-amber-500"
                        : "bg-emerald-500",
                  )}
                  style={{ width: `${Math.min(toMoney(bucket.share) * 100, 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </WidgetCard>
  );
}

// ---------------------------------------------------------------------------
// Suggest account code
// ---------------------------------------------------------------------------

export function SuggestAccountCode({ accounts = [] }: { accounts?: Account[] }) {
  const router = useRouter();
  const [description, setDescription] = useState("");
  const [suggestion, setSuggestion] = useState<AccountCodeSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    const input = description.trim();
    if (!input) return;
    setLoading(true);
    setError(null);
    try {
      setSuggestion(await suggestAccountCode(input));
    } catch (err) {
      setError(message(err, "Could not generate an account-code suggestion."));
      setSuggestion(null);
    } finally {
      setLoading(false);
    }
  }, [description]);

  const matchedAccount = suggestion
    ? accounts.find((a) => a.code === suggestion.suggested_code)
    : null;

  const accountTypeLabel = matchedAccount
    ? ACCOUNT_TYPE_LABELS[matchedAccount.account_type]
    : null;

  function goToJournalEntry() {
    if (!suggestion || !suggestion.suggested_code) return;
    const params = new URLSearchParams({
      draft_memo: suggestion.description || description,
      draft_account: suggestion.suggested_code,
    });
    if (suggestion.amount != null && suggestion.amount > 0) {
      params.set("draft_amount", String(suggestion.amount));
      params.set("draft_side", suggestion.side);
    }
    router.push(`/dashboard/erp/finance/journal-entries?${params.toString()}`);
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <Wand2 aria-hidden="true" className="size-4 text-primary" />
        <h3 className="font-display text-sm font-semibold text-foreground">Suggest account code</h3>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Describe the transaction and get a chart-of-accounts code suggestion.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="min-w-0 flex-1 space-y-1.5">
          <Label htmlFor="suggest-desc" className="sr-only">
            Transaction description
          </Label>
          <Input
            id="suggest-desc"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="e.g. Monthly software subscription"
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void run();
              }
            }}
          />
        </div>
        <Button type="button" disabled={loading || !description.trim()} onClick={() => void run()}>
          {loading ? (
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
          ) : (
            <Wand2 aria-hidden="true" className="size-4" />
          )}
          Suggest
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-xs font-medium text-destructive">
          {error}
        </p>
      ) : null}
      {suggestion ? (
        <div className="mt-3 rounded-lg bg-muted/50 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span>
              <span className="font-mono text-base font-semibold text-foreground">
                {suggestion.suggested_code}
              </span>
              <span className="ml-2 text-foreground">{suggestion.suggested_name}</span>
            </span>
            {accountTypeLabel ? (
              <span
                className={cn(
                  "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
                  matchedAccount?.account_type === "expense" &&
                    "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
                  matchedAccount?.account_type === "revenue" &&
                    "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
                  matchedAccount?.account_type === "asset" &&
                    "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
                  matchedAccount?.account_type === "liability" &&
                    "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
                  matchedAccount?.account_type === "equity" &&
                    "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
                )}
              >
                {accountTypeLabel}
              </span>
            ) : null}
            <span className="ml-auto text-xs text-muted-foreground">
              {Math.round(toMoney(suggestion.confidence) * 100)}% confidence
            </span>
          </div>
          {suggestion.amount != null && suggestion.amount > 0 ? (
            <p className="mt-1 text-xs text-muted-foreground">
              {suggestion.side === "credit" ? "Credit" : "Debit"}:{" "}
              <span className="font-mono font-semibold text-foreground">
                {formatMoney(suggestion.amount)}
              </span>
            </p>
          ) : null}
          <p className="mt-2 text-xs text-muted-foreground">
            {suggestion.reasoning ||
              "No explanation available. The suggestion above is based on keyword matching."}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={goToJournalEntry}
          >
            <SquarePen aria-hidden="true" className="size-3.5" />
            Create journal entry
          </Button>
        </div>
      ) : null}
    </div>
  );
}
