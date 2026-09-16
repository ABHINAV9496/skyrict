"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ClipboardCheck, Gauge, Search, TrendingDown, Users } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { FilterChipGroup } from "@/components/dashboard/shared/filter-chip-group";
import { StatCard } from "@/components/dashboard/shared/stat-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  getQualityOrgKpi,
  listQualityScores,
  type EmployeeQualityScore,
  type QualityGrade,
  type QualityOrgKpi,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useLatestRequest } from "@/lib/hooks/use-latest-request";

const PAGE_SIZE = 20;

const GRADE_STYLES: Record<QualityGrade, string> = {
  A: "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  B: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
  C: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  D: "bg-orange-500/15 text-orange-700 ring-1 ring-orange-500/30 dark:text-orange-400",
  F: "bg-destructive/10 text-destructive ring-1 ring-destructive/30",
};

const GRADE_BAR: Record<QualityGrade, string> = {
  A: "bg-emerald-500",
  B: "bg-sky-500",
  C: "bg-amber-500",
  D: "bg-orange-500",
  F: "bg-destructive",
};

const GRADE_ORDER: QualityGrade[] = ["A", "B", "C", "D", "F"];

const GRADE_HINT: Record<QualityGrade, string> = {
  A: "Complete",
  B: "Minor gaps",
  C: "Some gaps",
  D: "Needs attention",
  F: "Critical gaps",
};

function GradeBadge({ grade }: { grade: QualityGrade }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        GRADE_STYLES[grade] ?? GRADE_STYLES.F,
      )}
    >
      {grade}
    </span>
  );
}

/** "missing_email" → "missing email" the raw codes shown in the tooltip. */
function humanizeIssue(issue: string): string {
  const [, qualifier] = issue.split(":", 2);
  const code = qualifier ?? issue;
  return code.replaceAll("_", " ");
}

function issuesSummary(issues: EmployeeQualityScore["issues"]): string {
  return [...issues.mandatory, ...issues.contact, ...issues.document]
    .map(humanizeIssue)
    .join(", ");
}

function percent(score: number, max: number): string {
  return `${Math.round((score / max) * 100)}%`;
}

function initials(value: string): string {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      kpi: QualityOrgKpi | null;
      scores: EmployeeQualityScore[];
      totalPages: number;
      /** Set when the L2 list is off-limits (`erp.hr.ai.individual` absent). */
      individualBlocked: string | null;
      listError: string | null;
    };

export function DataQualityClient() {
  const router = useRouter();
  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [gradeFilter, setGradeFilter] = useState<"all" | QualityGrade>("all");

  const requestGuard = useLatestRequest();

  const load = useCallback(async () => {
    const requestId = requestGuard.next();
    setStatus({ state: "loading" });
    const [kpiResult, listResult] = await Promise.allSettled([
      getQualityOrgKpi(),
      listQualityScores({ page, pageSize: PAGE_SIZE }),
    ]);

    if (kpiResult.status === "rejected") {
      const error = kpiResult.reason;
      if (!requestGuard.isCurrent(requestId)) return;
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load data quality.",
      });
      return;
    }

    let scores: EmployeeQualityScore[] = [];
    let totalPages = 1;
    let individualBlocked: string | null = null;
    let listError: string | null = null;
    if (listResult.status === "rejected") {
      const error = listResult.reason;
      if (error instanceof ApiError && error.status === 403) {
        individualBlocked =
          "Per-employee scores need the erp.hr.ai.individual permission the aggregate view below is still available.";
      } else {
        listError =
          error instanceof ApiError ? error.message : "Could not load the employee table.";
      }
    } else {
      scores = listResult.value.items;
      totalPages = listResult.value.meta.total_pages;
    }

    if (!requestGuard.isCurrent(requestId)) return;
    setStatus({
      state: "ready",
      kpi: kpiResult.value,
      scores,
      totalPages,
      individualBlocked,
      listError,
    });
  }, [page, requestGuard]);

  useEffect(() => {
    void load();
  }, [load]);

  const gradeOptions = useMemo<{ value: string; label: string }[]>(
    () => [
      { value: "all", label: "All grades" },
      ...GRADE_ORDER.map((grade) => ({
        value: grade,
        label: `${grade}${kpiGradeCount(status, grade) > 0 ? ` · ${kpiGradeCount(status, grade)}` : ""}`,
      })),
    ],
    [status],
  );

  function kpiGradeCount(current: PageStatus, grade: QualityGrade): number {
    return current.state === "ready" && current.kpi
      ? (current.kpi.gradeDistribution[grade] ?? 0)
      : 0;
  }

  const filtered = useMemo(() => {
    if (status.state !== "ready") return [];
    const needle = query.trim().toLowerCase();
    return status.scores.filter((row) => {
      if (gradeFilter !== "all" && row.grade !== gradeFilter) return false;
      if (!needle) return true;
      const haystack = [
        row.name ?? "",
        row.employeeNumber ?? "",
        row.departmentName ?? "",
        ...row.issues.mandatory,
        ...row.issues.contact,
        ...row.issues.document,
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [status, query, gradeFilter]);

  const columns: ErpColumn<EmployeeQualityScore>[] = [
    {
      key: "employeeId",
      label: "Employee",
      render: (row) => (
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary-foreground">
            {row.name ? initials(row.name) : "?"}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium text-foreground">
              {row.name ?? row.employeeId}
            </span>
            {row.employeeNumber ? (
              <span className="tabular-nums text-xs text-muted-foreground">
                {row.employeeNumber}
              </span>
            ) : null}
          </span>
        </div>
      ),
    },
    {
      key: "departmentName",
      label: "Department",
      render: (row) => (
        <span className="text-muted-foreground">{row.departmentName ?? "Unassigned"}</span>
      ),
    },
    {
      key: "grade",
      label: "Grade",
      render: (row) => <GradeBadge grade={row.grade} />,
    },
    {
      key: "mandatoryScore",
      label: "Identity",
      align: "right",
      render: (row) => (
        <span className="tabular-nums">{percent(row.mandatoryScore, 0.5)}</span>
      ),
    },
    {
      key: "contactScore",
      label: "Contact",
      align: "right",
      render: (row) => (
        <span className="tabular-nums">{percent(row.contactScore, 0.25)}</span>
      ),
    },
    {
      key: "documentScore",
      label: "Documents",
      align: "right",
      render: (row) => (
        <span className="tabular-nums">{percent(row.documentScore, 0.25)}</span>
      ),
    },
    {
      key: "score",
      label: "Overall",
      align: "right",
      render: (row) => (
        <span className="font-medium tabular-nums">{percent(row.score, 1)}</span>
      ),
    },
    {
      key: "issues",
      label: "Issues",
      render: (row) => {
        const all = [...row.issues.mandatory, ...row.issues.contact, ...row.issues.document];
        if (all.length === 0) return <span className="text-muted-foreground">None</span>;
        const shown = all.slice(0, 2);
        return (
          <span className="flex flex-wrap items-center gap-1">
            {shown.map((issue) => (
              <span
                key={issue}
                className="inline-flex max-w-40 truncate rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {humanizeIssue(issue)}
              </span>
            ))}
            {all.length > shown.length ? (
              <span
                title={issuesSummary(row.issues)}
                className="inline-flex rounded-full border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground"
              >
                +{all.length - shown.length}
              </span>
            ) : null}
          </span>
        );
      },
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Data quality"
          description="How complete every employee's record is identity, contact, and documents."
          icon={ClipboardCheck}
        />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
        </div>
        <ErpDataTableSkeleton columns={8} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Data quality"
          description="How complete every employee's record is identity, contact, and documents."
          icon={ClipboardCheck}
        />
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-destructive">{status.message}</p>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const { kpi, totalPages } = status;
  const needsAttention = kpi
    ? (kpi.gradeDistribution["D"] ?? 0) + (kpi.gradeDistribution["F"] ?? 0)
    : 0;
  const lowestGrade =
    kpi && kpi.totalScored > 0
      ? ([...GRADE_ORDER].reverse().find((grade) => (kpi.gradeDistribution[grade] ?? 0) > 0) ??
        "-")
      : "-";

  const segmentTotal = kpi
    ? GRADE_ORDER.reduce((sum, grade) => sum + (kpi.gradeDistribution[grade] ?? 0), 0)
    : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data quality"
        description="How complete every employee's record is identity, contact, and documents."
        icon={ClipboardCheck}
      />

      {kpi ? (
        <section aria-label="Data-quality summary" className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              icon={Users}
              label="Scored employees"
              value={String(kpi.totalScored)}
              hint="Records included in scoring"
            />
            <StatCard
              icon={Gauge}
              label="Average score"
              value={kpi.totalScored > 0 ? percent(kpi.averageScore, 1) : "-"}
              hint="Across identity, contact, documents"
            />
            <StatCard
              icon={TrendingDown}
              label="Lowest grade present"
              value={String(lowestGrade)}
              hint="Worst record in the org"
              tone="warning"
            />
            <StatCard
              icon={AlertTriangle}
              label="Needs attention"
              value={String(needsAttention)}
              hint="D or F grades"
              tone={needsAttention > 0 ? "destructive" : "success"}
            />
          </div>

          {segmentTotal > 0 ? (
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
                  Grades across the org
                </h2>
                <p className="text-xs text-muted-foreground">
                  Tap a segment to filter the table below
                </p>
              </div>
              <div className="mt-4 flex h-3 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label="Grade distribution">
                {GRADE_ORDER.map((grade) => {
                  const count = kpi.gradeDistribution[grade] ?? 0;
                  if (count === 0) return null;
                  return (
                    <button
                      key={grade}
                      type="button"
                      onClick={() => setGradeFilter(gradeFilter === grade ? "all" : grade)}
                      aria-label={`Filter to grade ${grade}`}
                      className={cn(
                        GRADE_BAR[grade],
                        "h-full transition-opacity hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        gradeFilter !== "all" && gradeFilter !== grade && "opacity-30",
                      )}
                      style={{ width: `${(count / segmentTotal) * 100}%` }}
                    />
                  );
                })}
              </div>
              <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
                {GRADE_ORDER.map((grade) => {
                  const count = kpi.gradeDistribution[grade] ?? 0;
                  const active = gradeFilter === grade;
                  return (
                    <li key={grade}>
                      <button
                        type="button"
                        onClick={() => setGradeFilter(active ? "all" : grade)}
                        className={cn(
                          "flex items-center gap-1.5 rounded-full px-1.5 py-0.5 text-xs transition-colors hover:bg-muted",
                          active ? "font-semibold text-foreground" : "text-muted-foreground",
                        )}
                      >
                        <span className={cn("size-2 rounded-full", GRADE_BAR[grade])} aria-hidden="true" />
                        {grade} · {count}
                        <span className="hidden sm:inline"> — {GRADE_HINT[grade]}</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}

          <div className="rounded-xl border border-border bg-card p-5">
            <p className="text-sm text-muted-foreground">{kpi.narrative}</p>
            {kpi.departmentAverages.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-2">
                {kpi.departmentAverages.map((dept) => (
                  <span
                    key={dept.departmentName}
                    className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-xs"
                  >
                    <span className="font-medium text-foreground">{dept.departmentName}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {percent(dept.averageScore, 1)}
                    </span>
                    {dept.lowQualityCount > 0 ? (
                      <span className="text-destructive">{dept.lowQualityCount} low</span>
                    ) : null}
                  </span>
                ))}
              </div>
            ) : null}
            <p className="mt-3 text-xs text-muted-foreground">
              As of {formatDateTime(kpi.generatedAt)}
            </p>
          </div>
        </section>
      ) : null}

      <section aria-label="Per-employee scores" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            Employees by score
          </h2>
          <p className="text-xs text-muted-foreground">
            Identity 50% · Contact 25% · Documents 25%
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-64">
            <Search
              aria-hidden="true"
              className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-8"
              placeholder="Search name, dept, issue…"
              aria-label="Search employees"
            />
          </div>
          <FilterChipGroup
            options={gradeOptions}
            value={gradeFilter}
            onChange={(value) => setGradeFilter(value as "all" | QualityGrade)}
            ariaLabel="Filter by grade"
          />
        </div>

        {status.individualBlocked ? (
          <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            {status.individualBlocked}
          </p>
        ) : null}
        {status.listError ? (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs font-medium text-destructive">
            {status.listError}
          </p>
        ) : null}

        {status.individualBlocked || status.listError ? null : filtered.length === 0 ? (
          <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            No employees match this filter on the current page.
          </p>
        ) : (
          <ErpDataTable
            columns={columns}
            rows={filtered}
            meta={{
              total: filtered.length,
              page,
              page_size: PAGE_SIZE,
              total_pages: totalPages,
            }}
            onPageChange={setPage}
            onRowClick={(row) => router.push(`/dashboard/erp/hr/employees/${row.employeeId}`)}
          />
        )}
      </section>
    </div>
  );
}
