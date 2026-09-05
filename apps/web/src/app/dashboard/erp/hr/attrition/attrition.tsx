"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, TrendingDown } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  acknowledgeAttrition,
  getAttrition,
  type HrAttritionSummary,
  type HrAttritionView,
  type HrDepartmentRisk,
  type HrEmployeeRisk,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const BAND_STYLES: Record<string, string> = {
  high: "bg-destructive/10 text-destructive ring-1 ring-destructive/30",
  medium: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  low: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
};

const BAND_LABEL: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

function BandBadge({ band }: { band: string }) {
  return (
    <Badge
      variant="outline"
      className={cn("capitalize", BAND_STYLES[band] ?? "bg-muted text-muted-foreground")}
    >
      {BAND_LABEL[band] ?? band}
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

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function signed(value: number): string {
  const formatted = value.toFixed(2);
  return value > 0 ? `+${formatted}` : formatted;
}

function departmentRisk(employees: HrEmployeeRisk[]): HrDepartmentRisk[] {
  const byDept = new Map<string, HrEmployeeRisk[]>();
  for (const employee of employees) {
    const name = employee.departmentName ?? "Unassigned";
    byDept.set(name, [...(byDept.get(name) ?? []), employee]);
  }
  return [...byDept.entries()]
    .map(([name, rows]) => ({
      departmentName: name,
      highRiskCount: rows.filter((row) => row.riskBand === "high").length,
      totalScores: rows.length,
      averageRisk: rows.length
        ? Number((rows.reduce((sum, row) => sum + row.score, 0) / rows.length).toFixed(4))
        : 0,
    }))
    .sort(
      (a, b) => b.highRiskCount - a.highRiskCount || b.averageRisk - a.averageRisk,
    );
}

function SummaryCards({
  summary,
  narrative,
}: {
  summary: HrAttritionSummary;
  narrative?: string;
}) {
  return (
    <section aria-label="Attrition summary" className="space-y-4">
      <div className="flex items-center gap-2">
        <L1Badge />
        <p className="text-xs text-muted-foreground">Aggregated counts only — no per-person data.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">High risk</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-destructive">
            {summary.highRiskCount}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Medium risk</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-amber-600 dark:text-amber-400">
            {summary.mediumRiskCount}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Low risk</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums text-sky-600 dark:text-sky-400">
            {summary.lowRiskCount}
          </p>
        </div>
      </div>
      {summary.topRiskDepartments.length > 0 ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Top-risk departments</p>
          <div className="mt-2 space-y-1.5">
            {summary.topRiskDepartments.map((dept) => (
              <div key={dept.departmentName} className="flex items-center justify-between gap-2 text-sm">
                <span className="text-muted-foreground">{dept.departmentName}</span>
                <span className="font-medium tabular-nums text-foreground">
                  {dept.highRiskCount}/{dept.totalScores} high · avg {percent(dept.averageRisk)}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {narrative || summary.generatedAt ? (
        <div className="rounded-xl border border-border bg-card p-4">
          {narrative ? <p className="text-sm text-muted-foreground">{narrative}</p> : null}
          {summary.generatedAt ? (
            <p className="mt-2 text-xs text-muted-foreground">As of {formatDateTime(summary.generatedAt)}</p>
          ) : null}
          {summary.modelVersion ? (
            <p className="mt-1 text-xs text-muted-foreground">Model {summary.modelVersion}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

type Column = "band" | "employee" | "probability" | "factors" | "status";

function EmployeeTable({
  employees,
  onAcknowledge,
  ackState,
}: {
  employees: HrEmployeeRisk[];
  onAcknowledge: (employeeId: string) => void;
  ackState: Record<string, { busy?: boolean; error?: string }>;
}) {
  if (employees.length === 0) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        No attrition scores yet — the model has not scored any employee.
      </p>
    );
  }
  const columns: Column[] = ["employee", "band", "probability", "factors", "status"];
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
            {columns.map((column) => (
              <th key={column} className="px-4 py-3 font-medium">
                {column === "employee" ? "Employee" : column === "band" ? "Risk" : column === "probability" ? "Probability" : column === "factors" ? "Top factors" : "Status"}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {employees.map((employee) => {
            const state = ackState[employee.employeeId];
            return (
              <tr key={employee.employeeId}>
                <td className="px-4 py-3">
                  <p className="font-medium text-foreground">{employee.name ?? "Unnamed employee"}</p>
                  <p className="text-xs text-muted-foreground">
                    {employee.employeeNumber ?? ""}
                    {employee.employeeNumber && employee.departmentName ? " · " : ""}
                    {employee.departmentName ?? ""}
                  </p>
                </td>
                <td className="px-4 py-3">
                  <BandBadge band={employee.riskBand} />
                </td>
                <td className="px-4 py-3">
                  <p className="font-semibold tabular-nums text-foreground">{percent(employee.score)}</p>
                  <p className="text-xs text-muted-foreground">confidence {percent(employee.confidence)}</p>
                </td>
                <td className="px-4 py-3">
                  {employee.factors.length > 0 ? (
                    <ul className="space-y-0.5">
                      {employee.factors.map((factor) => (
                        <li key={factor.feature} className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{factor.feature.replaceAll("_", " ")}</span>
                          <span className="font-medium tabular-nums text-foreground">
                            {signed(factor.contribution)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">No factors reported</p>
                  )}
                </td>
                <td className="px-4 py-3">
                  {employee.acknowledged ? (
                    <div className="flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 aria-hidden="true" className="size-4" />
                      <span>
                        Acknowledged{employee.acknowledgedAt ? ` ${formatDateTime(employee.acknowledgedAt)}` : ""}
                      </span>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={state?.busy}
                        onClick={() => onAcknowledge(employee.employeeId)}
                      >
                        {state?.busy ? "Acknowledging…" : "Acknowledge"}
                      </Button>
                      {state?.error ? (
                        <p className="max-w-56 text-xs font-medium text-destructive">{state.error}</p>
                      ) : null}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function AttritionClient() {
  const [view, setView] = useState<
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "summary"; summary: HrAttritionSummary }
    | { state: "detail"; generatedAt: string; modelVersion: string; employees: HrEmployeeRisk[] }
  >({ state: "loading" });
  const [ackState, setAckState] = useState<Record<string, { busy?: boolean; error?: string }>>({});

  const load = useCallback(async () => {
    setView({ state: "loading" });
    try {
      const result: HrAttritionView = await getAttrition();
      if (result.mode === "summary") {
        setView({ state: "summary", summary: result.summary });
      } else {
        setView({
          state: "detail",
          generatedAt: result.generatedAt,
          modelVersion: result.modelVersion,
          employees: result.employees,
        });
      }
    } catch (error) {
      setView({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load attrition risk.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleAcknowledge = useCallback((employeeId: string) => {
    setAckState((current) => ({ ...current, [employeeId]: { busy: true, error: undefined } }));
    acknowledgeAttrition(employeeId)
      .then(() => {
        setView((current) =>
          current.state === "detail"
            ? {
                ...current,
                employees: current.employees.map((employee) =>
                  employee.employeeId === employeeId
                    ? { ...employee, acknowledged: true, acknowledgedAt: new Date().toISOString() }
                    : employee,
                ),
              }
            : current,
        );
        setAckState((current) => ({ ...current, [employeeId]: { busy: false } }));
      })
      .catch((error) => {
        setAckState((current) => ({
          ...current,
          [employeeId]: {
            busy: false,
            error:
              error instanceof ApiError && error.status === 403
                ? "Acknowledgement needs the erp.hr.ai.acknowledge permission."
                : error instanceof ApiError
                  ? error.message
                  : "Could not acknowledge this employee.",
          },
        }));
      });
  }, []);

  const detailSummary: HrAttritionSummary | null =
    view.state === "detail"
      ? {
          generatedAt: view.generatedAt,
          modelVersion: view.modelVersion,
          highRiskCount: view.employees.filter((employee) => employee.riskBand === "high").length,
          mediumRiskCount: view.employees.filter((employee) => employee.riskBand === "medium").length,
          lowRiskCount: view.employees.filter((employee) => employee.riskBand === "low").length,
          topRiskDepartments: departmentRisk(view.employees),
          narrative: "",
        }
      : null;

  const sortedEmployees =
    view.state === "detail"
      ? [...view.employees].sort((a, b) => b.score - a.score)
      : [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attrition risk"
        description="Modelled retention risk per employee, scored on demand against the bundled attrition model."
        icon={TrendingDown}
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
          <div className="grid gap-4 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-card" />
            ))}
          </div>
          <div className="h-40 animate-pulse rounded-xl border border-border bg-card" />
        </div>
      ) : null}

      {view.state === "summary" ? (
        <>
          <SummaryCards summary={{ ...view.summary, modelVersion: view.summary.modelVersion }} />
          <section aria-label="Individual scores locked" className="rounded-xl border border-border bg-card p-4">
            <div className="flex items-center gap-2">
              <L2Badge />
              <p className="text-xs text-muted-foreground">
                Per-employee drill-down needs the erp.hr.ai.individual permission — the aggregate
                overview above is still available.
              </p>
            </div>
          </section>
        </>
      ) : null}

      {view.state === "detail" ? (
        <>
          <SummaryCards
            summary={detailSummary as HrAttritionSummary}
            narrative={detailSummary?.narrative}
          />
          <section aria-label="Per-employee attrition risk" className="space-y-3">
            <div className="flex items-center gap-2">
              <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                Per-employee risk
              </h2>
              <L2Badge />
              <p className="ml-auto hidden text-xs text-muted-foreground sm:block">
                {view.employees.length} scored employee(s)
              </p>
            </div>
            <EmployeeTable
              employees={sortedEmployees}
              onAcknowledge={handleAcknowledge}
              ackState={ackState}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}