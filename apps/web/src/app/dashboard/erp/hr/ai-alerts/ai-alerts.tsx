"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BarChart3, CalendarClock, ShieldAlert } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  getAnomalySummary,
  getEmployeeAnomalies,
  getEmployeeUtilization,
  getUtilizationSummary,
  listEmployees,
  type Employee,
  type HrAnomalyOrg,
  type HrLeaveAnomaly,
  type HrUtilizationAlert,
  type HrUtilizationOrg,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

type Tab = "utilization" | "anomaly";

const SEVERITY_STYLES: Record<string, string> = {
  high: "bg-destructive/10 text-destructive ring-1 ring-destructive/30",
  medium: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  low: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
};

const SEVERITY_LABEL: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

function humanize(code: string): string {
  return code.replaceAll("_", " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", SEVERITY_STYLES[severity] ?? "bg-muted text-muted-foreground")}
    >
      {SEVERITY_LABEL[severity] ?? humanize(severity)}
    </Badge>
  );
}

function L1Badge() {
  return (
    <Badge
      variant="outline"
      className="border-indigo-500/30 bg-indigo-500/10 text-indigo-700 dark:text-indigo-400"
    >
      L1 aggregate
    </Badge>
  );
}

function L2Badge() {
  return (
    <Badge
      variant="outline"
      className="border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-400"
    >
      L2 individual
    </Badge>
  );
}

function SummaryCards({
  total,
  byType,
  bySeverity,
  generatedAt,
  narrative,
}: {
  total: number;
  byType: Record<string, number>;
  bySeverity: Record<string, number>;
  generatedAt: string;
  narrative: string;
}) {
  const typeEntries = Object.entries(byType).sort((a, b) => b[1] - a[1]);
  return (
    <section aria-label="Alert summary" className="space-y-4">
      <div className="flex items-center gap-2">
        <L1Badge />
        <p className="text-xs text-muted-foreground">Aggregated counts only — no per-person data.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Total</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{total}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">By type</p>
          <div className="mt-2 space-y-1.5">
            {typeEntries.length > 0 ? (
              typeEntries.map(([type, count]) => (
                <div key={type} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-muted-foreground">{humanize(type)}</span>
                  <span className="font-medium tabular-nums text-foreground">{count}</span>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">None</p>
            )}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">By severity</p>
          <div className="mt-2 space-y-1.5">
            {Object.entries(bySeverity).length > 0 ? (
              Object.entries(bySeverity).map(([severity, count]) => (
                <div key={severity} className="flex items-center justify-between gap-2 text-sm">
                  <SeverityBadge severity={severity} />
                  <span className="font-medium tabular-nums text-foreground">{count}</span>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">None</p>
            )}
          </div>
        </div>
      </div>
      {narrative ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">{narrative}</p>
          {generatedAt ? (
            <p className="mt-2 text-xs text-muted-foreground">As of {formatDateTime(generatedAt)}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

type DetailState =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "blocked"; message: string }
  | { state: "error"; message: string }
  | { state: "ready"; rows: HrUtilizationAlert[] | HrLeaveAnomaly[] };

export function AiAlertsClient() {
  const [tab, setTab] = useState<Tab>("utilization");
  const [summary, setSummary] = useState<{ util: HrUtilizationOrg | null; anomaly: HrAnomalyOrg | null } | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [detail, setDetail] = useState<Record<Tab, DetailState>>({
    utilization: { state: "idle" },
    anomaly: { state: "idle" },
  });

  const loadSummary = useCallback(async () => {
    setSummaryError(null);
    const [util, anomaly] = await Promise.allSettled([getUtilizationSummary(), getAnomalySummary()]);
    if (util.status === "rejected" && anomaly.status === "rejected") {
      const error = util.reason;
      setSummaryError(
        error instanceof ApiError ? error.message : "Could not load HR AI alerts.",
      );
      return;
    }
    setSummary({
      util: util.status === "fulfilled" ? util.value : null,
      anomaly: anomaly.status === "fulfilled" ? anomaly.value : null,
    });
  }, []);

  const loadEmployees = useCallback(async () => {
    try {
      const result = await listEmployees({ pageSize: 200, filters: { status: "active" } });
      setEmployees(result.items);
    } catch {
      setEmployees((current) => current);
    }
  }, []);

  useEffect(() => {
    void loadSummary();
    void loadEmployees();
  }, [loadSummary, loadEmployees]);

  const loadDetail = useCallback(
    async (nextTab: Tab, employeeId: string) => {
      setDetail((current) => ({ ...current, [nextTab]: { state: "loading" } }));
      try {
        const rows =
          nextTab === "utilization"
            ? await getEmployeeUtilization(employeeId)
            : await getEmployeeAnomalies(employeeId);
        setDetail((current) => ({ ...current, [nextTab]: { state: "ready", rows } }));
      } catch (error) {
        if (error instanceof ApiError && error.status === 403) {
          setDetail((current) => ({
            ...current,
            [nextTab]: {
              state: "blocked",
              message:
                "Per-employee alerts need the erp.hr.ai.individual permission — the aggregate overview above is still available.",
            },
          }));
        } else {
          setDetail((current) => ({
            ...current,
            [nextTab]: {
              state: "error",
              message: error instanceof ApiError ? error.message : "Could not load employee alerts.",
            },
          }));
        }
      }
    },
    [],
  );

  const handleSelect = useCallback(
    (employeeId: string) => {
      setSelectedId(employeeId);
      if (employeeId) void loadDetail(tab, employeeId);
    },
    [loadDetail, tab],
  );

  const handleTab = useCallback(
    (nextTab: Tab) => {
      setTab(nextTab);
      if (selectedId && detail[nextTab].state === "idle") {
        void loadDetail(nextTab, selectedId);
      }
    },
    [detail, loadDetail, selectedId],
  );

  const currentSummary = tab === "utilization" ? summary?.util : summary?.anomaly;
  const currentDetail = detail[tab];
  const maxEmployees = useMemo(() => employees.length, [employees]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI alerts"
        description="Leave-balance utilization risks and leave-pattern anomalies detected across the team."
        icon={BarChart3}
      />

      <div className="flex items-center gap-1 rounded-xl border border-border bg-card p-1">
        <button
          type="button"
          onClick={() => handleTab("utilization")}
          className={cn(
            "flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
            tab === "utilization"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted",
          )}
        >
          <CalendarClock aria-hidden="true" className="size-4" />
          Utilization
        </button>
        <button
          type="button"
          onClick={() => handleTab("anomaly")}
          className={cn(
            "flex flex-1 items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
            tab === "anomaly"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted",
          )}
        >
          <ShieldAlert aria-hidden="true" className="size-4" />
          Leave anomalies
        </button>
      </div>

      {summaryError ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-destructive">{summaryError}</p>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void loadSummary()}>
            Try again
          </Button>
        </div>
      ) : summary && currentSummary ? (
        <>
          <SummaryCards
            total={
              tab === "utilization"
                ? (currentSummary as HrUtilizationOrg).totalAlerts
                : (currentSummary as HrAnomalyOrg).totalAnomalies
            }
            byType={currentSummary.byType}
            bySeverity={currentSummary.bySeverity}
            generatedAt={currentSummary.generatedAt}
            narrative={currentSummary.narrative}
          />

          <section aria-label="Employee alerts" className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                  Per-employee alerts
                </h2>
                <L2Badge />
              </div>
              <Select value={selectedId || "none"} onValueChange={handleSelect}>
                <SelectTrigger className="w-[280px]" aria-label="Employee">
                  <SelectValue placeholder={`Select an employee (${maxEmployees} available)`} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none" disabled>
                    Select an employee
                  </SelectItem>
                  {employees.map((employee) => (
                    <SelectItem key={employee.id} value={employee.id}>
                      {employee.firstName} {employee.lastName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {currentDetail.state === "blocked" ? (
              <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                {currentDetail.message}
              </p>
            ) : null}
            {currentDetail.state === "error" ? (
              <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs font-medium text-destructive">
                {currentDetail.message}
              </p>
            ) : null}

            {selectedId && currentDetail.state !== "idle" ? (
              <div className="overflow-hidden rounded-xl border border-border bg-card">
                {currentDetail.state === "loading" ? (
                  <div className="space-y-2 p-4">
                    <div className="h-14 animate-pulse rounded-lg bg-muted" />
                    <div className="h-14 animate-pulse rounded-lg bg-muted" />
                  </div>
                ) : null}
                {currentDetail.state === "ready" && currentDetail.rows.length === 0 ? (
                  <p className="p-4 text-sm text-muted-foreground">
                    No open {tab === "utilization" ? "utilization alerts" : "leave anomalies"} for this employee.
                  </p>
                ) : null}
                {currentDetail.state === "ready" && currentDetail.rows.length > 0 ? (
                  <ul className="divide-y divide-border">
                    {currentDetail.rows.map((row, index) => {
                      const isAlert = tab === "utilization";
                      const alert = row as HrUtilizationAlert;
                      const anomaly = row as HrLeaveAnomaly;
                      return (
                        <li key={`${tab}-${index}`} className="flex items-start justify-between gap-4 p-4">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-foreground">
                                {isAlert ? humanize(alert.alertType) : anomaly.title}
                              </span>
                              <SeverityBadge severity={isAlert ? alert.severity : anomaly.severity} />
                              {isAlert && alert.leaveType ? (
                                <span className="text-xs text-muted-foreground">
                                  {humanize(alert.leaveType)}
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-1 text-sm text-muted-foreground">
                              {isAlert
                                ? `${alert.balanceDays} day(s) balance` +
                                  (alert.projectedForfeitureDays != null
                                    ? `, ${alert.projectedForfeitureDays} projected to forfeit`
                                    : "") +
                                  (alert.daysRemainingInYear != null
                                    ? `, ${alert.daysRemainingInYear} day(s) left in year`
                                    : "")
                                : anomaly.description}
                            </p>
                            {!isAlert && anomaly.teamSize > 0 ? (
                              <p className="mt-1 text-xs text-muted-foreground">
                                Team of {anomaly.teamSize}
                              </p>
                            ) : null}
                          </div>
                          <div className="shrink-0 text-right text-xs text-muted-foreground">
                            <p>{row.name}</p>
                            <p>{row.departmentName ?? "Unassigned"}</p>
                            <p>{formatDateTime(row.createdAt)}</p>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </div>
            ) : (
              currentDetail.state === "idle" && (
                <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                  Pick an employee to view their per-person alerts.
                </p>
              )
            )}
          </section>
        </>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-card" />
            ))}
          </div>
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
        </div>
      )}
    </div>
  );
}