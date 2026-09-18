"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, BarChart3, SlidersHorizontal } from "lucide-react";

import { ChartSkeleton } from "@/components/charts/chart-skeleton";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { RequirePermission } from "@/components/dashboard/shared/require-permission";
import { ListPageSkeleton, TableSkeleton } from "@/components/ui/page-skeletons";
import {
  REPORT_MODULE_LABELS,
  exportReport,
  getReport,
  listSnapshots,
  normalizeModule,
  runReport,
  type ReportDefinition,
  type ReportRunResult,
} from "@/lib/api/reports-api";
import { ApiError } from "@/lib/api/http";
import { formatDateTime } from "@/lib/format";
import { planChart } from "@/lib/reports/chartability";
import { saveReportCsv } from "@/lib/reports/export";
import {
  buildParamFields,
  initialParamValues,
  toQueryString,
  type ReportParamField,
} from "@/lib/reports/params";
import { setPageTitle } from "@/lib/topbar-title";
import { ReportParamForm } from "@/features/reports/components/report-param-form";
import { ReportResultsTable } from "@/features/reports/components/report-results-table";
import {
  ReportSnapshots,
  type SnapshotsState,
} from "@/features/reports/components/report-snapshots";

// recharts lives in the dynamically-imported chart chunk; ssr:false keeps it
// out of this report route's first-load JS and ChartSkeleton reserves height.
const LazyReportChart = dynamic(
  () =>
    import("@/features/reports/components/report-chart").then(
      (m) => m.ReportChart,
    ),
  { ssr: false, loading: ChartSkeleton },
);

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; report: ReportDefinition };

type RunState =
  | { status: "idle" }
  | { status: "running" }
  | { status: "error"; message: string }
  | { status: "ready"; result: ReportRunResult };

export function ReportsDetail({
  slug,
  initialParams,
}: {
  slug: string;
  initialParams: Record<string, string>;
}) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [values, setValues] = useState<Record<string, string>>({});
  const [runState, setRunState] = useState<RunState>({ status: "idle" });
  const [exporting, setExporting] = useState(false);
  const [view, setView] = useState<"table" | "chart">("table");
  const [snapshotsState, setSnapshotsState] = useState<SnapshotsState>({
    status: "loading",
  });
  const autoRunDone = useRef(false);

  const loadSnapshots = useCallback(async () => {
    setSnapshotsState({ status: "loading" });
    try {
      const items = await listSnapshots(slug, 20);
      setSnapshotsState({ status: "ready", items });
    } catch (error) {
      setSnapshotsState({
        status: "error",
        message:
          error instanceof ApiError ? error.message : "Could not load run history.",
      });
    }
  }, [slug]);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    void loadSnapshots();
    try {
      const report = await getReport(slug);
      setState({ status: "ready", report });
    } catch (error) {
      setState({
        status: "error",
        message:
          error instanceof ApiError ? error.message : "Could not load this report.",
      });
    }
  }, [loadSnapshots, slug]);

  useEffect(() => {
    void load();
  }, [load]);

  const fields = useMemo<ReportParamField[]>(
    () => (state.status === "ready" ? buildParamFields(state.report.params) : []),
    [state],
  );

  // Seed the form from the deep-linked URL, falling back to sensible defaults.
  useEffect(() => {
    if (state.status !== "ready") return;
    setValues((current) =>
      Object.keys(current).length > 0 ? current : initialParamValues(fields, initialParams),
    );
  }, [state, fields, initialParams]);

  useEffect(() => {
    if (state.status === "ready") setPageTitle(state.report.title);
    return () => setPageTitle(null);
  }, [state]);

  const run = useCallback(
    async (next: Record<string, string>) => {
      if (state.status !== "ready") return;
      const report = state.report;
      setRunState({ status: "running" });
      router.replace(`/dashboard/erp/reports/${slug}${toQueryString(next, report.params)}`, {
        scroll: false,
      });
      try {
        const result = await runReport(slug, next);
        setRunState({ status: "ready", result });
        void loadSnapshots();
      } catch (error) {
        setRunState({
          status: "error",
          message:
            error instanceof ApiError ? error.message : "Could not run this report.",
        });
      }
    },
    [loadSnapshots, router, slug, state],
  );

  // Deep links and parameter-less reports run themselves on first load; the
  // URL stays the source of truth for the parameters shown.
  useEffect(() => {
    if (state.status !== "ready" || autoRunDone.current) return;
    const hasDeepLink = Object.keys(initialParams).length > 0;
    if (!hasDeepLink && fields.length > 0) return;
    autoRunDone.current = true;
    void run(initialParamValues(fields, initialParams));
  }, [state, fields, initialParams, run]);

  const chartPlan = useMemo(
    () =>
      runState.status === "ready"
        ? planChart(runState.result.columns, runState.result.rows)
        : null,
    [runState],
  );

  const handleExport = useCallback(async () => {
    if (state.status !== "ready") return;
    setExporting(true);
    try {
      const res = await exportReport(slug, values);
      if (!res.ok) {
        const payload = (await res.json().catch(() => ({}))) as {
          detail?: { error?: { message?: string }; message?: string } | string;
        };
        const detail = payload.detail;
        const message =
          (typeof detail === "object" && detail?.error?.message) ||
          (typeof detail === "object" && detail?.message) ||
          (typeof detail === "string" ? detail : null) ||
          "Could not export the report.";
        throw new ApiError(res.status, message);
      }
      await saveReportCsv(res, `${slug}.csv`);
    } catch (error) {
      setRunState({
        status: "error",
        message:
          error instanceof ApiError ? error.message : "Could not export the report.",
      });
    } finally {
      setExporting(false);
    }
  }, [slug, values, state]);

  if (state.status === "loading") {
    return <ListPageSkeleton />;
  }

  if (state.status === "error") {
    return <ErrorState message={state.message} onRetry={() => void load()} />;
  }

  const { report } = state;

  return (
    <RequirePermission permission={report.permission_key}>
      <div className="space-y-6">
        <Link
          href="/dashboard/erp/reports"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          All reports
        </Link>

        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-primary">
            <BarChart3 aria-hidden="true" className="size-5" />
          </div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                {REPORT_MODULE_LABELS[normalizeModule(report.module)]}
              </span>
              <span className="text-xs text-muted-foreground">
                Updated {formatDateTime(report.updated_at)}
              </span>
            </div>
            <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">
              {report.title}
            </h1>
            <p className="text-sm text-muted-foreground">
              {report.description ?? "No description"}
            </p>
          </div>
        </div>

        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
          <ReportParamForm
            fields={fields}
            values={values}
            onChange={(name, value) =>
              setValues((current) => ({ ...current, [name]: value }))
            }
            onRun={() => void run(values)}
            onExport={() => void handleExport()}
            running={runState.status === "running"}
            exporting={exporting}
          />

          <div className="min-w-0 space-y-4">
            {runState.status === "idle" ? (
              <EmptyState
                icon={SlidersHorizontal}
                title="Configure this run"
                description="Set the report parameters and press Run to generate live results."
              />
            ) : null}
            {runState.status === "running" ? <TableSkeleton rows={6} /> : null}
            {runState.status === "error" ? (
              <ErrorState message={runState.message} onRetry={() => void run(values)} />
            ) : null}
            {runState.status === "ready" ? (
              <div className="space-y-4">
                {chartPlan ? (
                  <div className="flex gap-1.5">
                    {(
                      [
                        ["table", "Table"],
                        ["chart", "Chart"],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setView(key)}
                        className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                          view === key
                            ? "bg-primary text-primary-foreground"
                            : "text-muted-foreground hover:bg-muted hover:text-foreground"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                ) : null}
                {view === "chart" && chartPlan ? (
                  <LazyReportChart plan={chartPlan} rows={runState.result.rows} />
                ) : (
                  <ReportResultsTable result={runState.result} />
                )}
              </div>
            ) : null}
          </div>
        </div>

        <ReportSnapshots state={snapshotsState} onRetry={() => void loadSnapshots()} />
      </div>
    </RequirePermission>
  );
}