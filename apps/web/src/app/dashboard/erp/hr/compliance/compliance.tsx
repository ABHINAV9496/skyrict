"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";

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
  getComplianceSummary,
  getEmployeeComplianceFindings,
  listEmployees,
  setComplianceStatus,
  type Employee,
  type HrComplianceFinding,
  type HrComplianceSummary,
} from "@/lib/api/hr-api";
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

type DetailState =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "blocked"; message: string }
  | { state: "error"; message: string }
  | { state: "ready"; findings: HrComplianceFinding[] };

function FindingRow({
  finding,
  onStatusChange,
  statusState,
}: {
  finding: HrComplianceFinding;
  onStatusChange: (checkId: string, status: "acknowledged" | "resolved") => void;
  statusState: Record<string, { busy?: boolean; error?: string }>;
}) {
  const state = statusState[finding.checkId];

  return (
    <div className="flex items-start justify-between gap-4 p-4">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <Badge variant="outline">{TYPE_LABEL[finding.checkType] ?? finding.checkType}</Badge>
          {finding.status !== "open" ? (
            <Badge variant="secondary" className="capitalize">
              {finding.status}
            </Badge>
          ) : null}
        </div>
        <p className="text-sm font-medium text-foreground">{finding.title}</p>
        <p className="text-sm text-muted-foreground">{finding.description}</p>
        {finding.employeeNumber ? (
          <p className="text-xs text-muted-foreground">
            {finding.employeeNumber}
            {finding.name ? ` — ${finding.name}` : ""}
            {finding.departmentName ? ` (${finding.departmentName})` : ""}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {finding.status === "resolved" ? (
          <CheckCircle2 aria-hidden="true" className="size-5 text-green-600" />
        ) : finding.status === "open" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={state?.busy}
            onClick={() => onStatusChange(finding.checkId, "acknowledged")}
          >
            {state?.busy ? "Working…" : "Acknowledge"}
          </Button>
        ) : finding.status === "acknowledged" ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={state?.busy}
            onClick={() => onStatusChange(finding.checkId, "resolved")}
          >
            {state?.busy ? "Working…" : "Resolve"}
          </Button>
        ) : (
          <Badge variant="secondary" className="capitalize">
            {finding.status}
          </Badge>
        )}
        {state?.error ? (
          <p className="max-w-[220px] text-right text-xs font-medium text-destructive">{state.error}</p>
        ) : null}
      </div>
    </div>
  );
}

export function ComplianceClient() {
  const [view, setView] = useState<
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "summary"; summary: HrComplianceSummary }
  >({ state: "loading" });

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employeesError, setEmployeesError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string>("");

  const [detail, setDetail] = useState<DetailState>({ state: "idle" });
  const [statusState, setStatusState] = useState<Record<string, { busy?: boolean; error?: string }>>({});

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

  const loadEmployees = useCallback(async () => {
    try {
      const result = await listEmployees({ pageSize: 200, filters: { status: "active" } });
      setEmployees(result.items);
    } catch (error) {
      setEmployeesError(
        error instanceof ApiError ? error.message : "Could not load employee list.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
    void loadEmployees();
  }, [load, loadEmployees]);

  const loadDetail = useCallback((employeeId: string) => {
    setDetail({ state: "loading" });
    getEmployeeComplianceFindings(employeeId)
      .then((findings) => setDetail({ state: "ready", findings }))
      .catch((error) => {
        if (error instanceof ApiError && error.status === 403) {
          setDetail({
            state: "blocked",
            message:
              "Per-employee findings need the erp.hr.ai.individual permission — the aggregate overview above is still available.",
          });
        } else {
          setDetail({
            state: "error",
            message: error instanceof ApiError ? error.message : "Could not load compliance findings.",
          });
        }
      });
  }, []);

  const handleStatusChange = useCallback(
    (checkId: string, status: "acknowledged" | "resolved") => {
      setStatusState((current) => ({ ...current, [checkId]: { busy: true, error: undefined } }));

      setComplianceStatus(checkId, status)
        .then((updated) => {
          setDetail((current) =>
            current.state === "ready"
              ? {
                  ...current,
                  findings: current.findings.map((f) =>
                    f.checkId === checkId ? { ...f, status: updated.status } : f,
                  ),
                }
              : current,
          );
          setStatusState((current) => ({ ...current, [checkId]: { busy: false } }));

          // Keep L1 counts in sync with the L2 action.
          getComplianceSummary()
            .then((summary) => {
              setView((current) =>
                current.state === "summary" ? { ...current, summary } : current,
              );
            })
            .catch(() => {});
        })
        .catch((error) => {
          setStatusState((current) => ({
            ...current,
            [checkId]: {
              busy: false,
              error:
                error instanceof ApiError && error.status === 403
                  ? "Status change needs the erp.hr.ai.acknowledge permission."
                  : error instanceof ApiError
                    ? error.message
                    : "Could not update status.",
            },
          }));
        });
    },
    [],
  );

  const maxEmployees = employees.length;
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
            <section aria-label="Per-employee findings" className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                    Per-employee findings
                  </h2>
                  <Badge
                    variant="outline"
                    className="border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-400"
                  >
                    L2 individual
                  </Badge>
                </div>
                <Select
                  value={selectedId || "none"}
                  onValueChange={(value) => {
                    setSelectedId(value);
                    if (value !== "none") loadDetail(value);
                  }}
                >
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

              {employeesError ? (
                <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs font-medium text-destructive">
                  {employeesError}
                </p>
              ) : null}

              {detail.state === "blocked" ? (
                <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                  {detail.message}
                </p>
              ) : null}
              {detail.state === "error" ? (
                <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs font-medium text-destructive">
                  {detail.message}
                </p>
              ) : null}

              {selectedId && detail.state !== "idle" ? (
                <div className="overflow-hidden rounded-xl border border-border bg-card">
                  {detail.state === "loading" ? (
                    <div className="space-y-2 p-4">
                      <div className="h-20 animate-pulse rounded-lg bg-muted" />
                      <div className="h-20 animate-pulse rounded-lg bg-muted" />
                    </div>
                  ) : null}
                  {detail.state === "ready" && detail.findings.length === 0 ? (
                    <p className="p-4 text-sm text-muted-foreground">
                      No compliance findings for this employee.
                    </p>
                  ) : null}
                  {detail.state === "ready" && detail.findings.length > 0 ? (
                    <ul className="divide-y divide-border">
                      {detail.findings.map((finding) => (
                        <li key={finding.checkId}>
                          <FindingRow
                            finding={finding}
                            onStatusChange={handleStatusChange}
                            statusState={statusState}
                          />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : (
                detail.state === "idle" && (
                  <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                    Pick an employee to view their per-person compliance findings.
                  </p>
                )
              )}
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}
