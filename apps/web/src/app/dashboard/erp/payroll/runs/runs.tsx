"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LoaderCircle, Plus, Receipt } from "lucide-react";

import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useModuleAccess } from "@/lib/access/modules";
import {
  createPayrollRun,
  listPayrollRuns,
  type PayrollRun,
  type PayrollRunStatus,
} from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; runs: PayrollRun[]; totalPages: number };

type Notice = { tone: "success" | "error"; text: string };

const STATUS_OPTIONS: { value: "all" | PayrollRunStatus; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "computed", label: "Computed" },
  { value: "approved", label: "Approved" },
  { value: "paid", label: "Paid" },
  { value: "void", label: "Void" },
];

const PAGE_SIZE = 20;

export function RunsClient() {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.payroll.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<"all" | PayrollRunStatus>("all");
  const [notice, setNotice] = useState<Notice | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ periodStart: "", periodEnd: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listPayrollRuns({
        page,
        pageSize: PAGE_SIZE,
        status: statusFilter === "all" ? undefined : statusFilter,
      });
      setStatus({
        state: "ready",
        runs: result.items,
        totalPages: result.meta.total_pages,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load payroll runs.";
      setStatus({ state: "error", message });
    }
  }, [page, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ErpColumn<PayrollRun>[] = [
    {
      key: "runCode",
      label: "Run",
      render: (run) => (
        <div>
          <p className="font-medium text-foreground">{run.runCode}</p>
          <p className="text-xs text-muted-foreground">
            {formatDate(run.periodStart)} → {formatDate(run.periodEnd)}
          </p>
        </div>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (run) => <StatusBadge status={run.status} />,
    },
    {
      key: "totalGross",
      label: "Gross",
      align: "right",
      render: (run) => (
        <span className="tabular-nums text-muted-foreground">
          {run.totalGross ? formatMoney(run.totalGross.amount, run.totalGross.currency) : "—"}
        </span>
      ),
    },
    {
      key: "totalNet",
      label: "Net",
      align: "right",
      render: (run) => (
        <span className="tabular-nums font-medium text-foreground">
          {run.totalNet ? formatMoney(run.totalNet.amount, run.totalNet.currency) : "—"}
        </span>
      ),
    },
    {
      key: "createdAt",
      label: "Created",
      render: (run) => (
        <span className="text-muted-foreground">{formatDate(run.createdAt)}</span>
      ),
    },
  ];

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !canWrite) return;
    if (!form.periodStart || !form.periodEnd) {
      setFormError("Both a start and an end date are required.");
      return;
    }
    if (form.periodEnd < form.periodStart) {
      setFormError("The end date can't be before the start date.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const run = await createPayrollRun({
        periodStart: form.periodStart,
        periodEnd: form.periodEnd,
      });
      setCreateOpen(false);
      setForm({ periodStart: "", periodEnd: "" });
      setNotice({ tone: "success", text: `${run.runCode} created as a draft.` });
      await load();
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : "Could not create the run.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Payroll runs"
          description="Periods of pay — from draft through compute, approval, and payment."
          icon={Receipt}
        />
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" className="size-4" />
            New run
          </Button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={statusFilter}
          onValueChange={(value) => {
            setStatusFilter(value as "all" | PayrollRunStatus);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-40" aria-label="Filter by status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {notice ? (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={cn(
            "rounded-lg border px-3 py-2 text-sm font-medium",
            notice.tone === "error"
              ? "border-destructive/40 bg-destructive/5 text-destructive"
              : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
          )}
        >
          {notice.text}
        </div>
      ) : null}

      {status.state === "loading" ? <ErpDataTableSkeleton columns={5} /> : null}

      {status.state === "error" ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
          <p className="text-sm font-medium text-destructive">{status.message}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => void load()}
          >
            Try again
          </Button>
        </div>
      ) : null}

      {status.state === "ready" ? (
        <ErpDataTable
          columns={columns}
          rows={status.runs}
          meta={{
            total: status.runs.length,
            page,
            page_size: PAGE_SIZE,
            total_pages: status.totalPages,
          }}
          onPageChange={setPage}
          onRowClick={(run) => router.push(`/dashboard/erp/payroll/runs/${run.id}`)}
        />
      ) : null}

      <Dialog open={createOpen} onOpenChange={(open) => !saving && setCreateOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={(event) => void onSubmit(event)}>
            <DialogHeader>
              <DialogTitle>New payroll run</DialogTitle>
              <DialogDescription>
                Pick the pay period. The run starts as a draft so you can review
                it before computing.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="period-start">Period start</Label>
                <Input
                  id="period-start"
                  type="date"
                  value={form.periodStart}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, periodStart: event.target.value }))
                  }
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="period-end">Period end</Label>
                <Input
                  id="period-end"
                  type="date"
                  value={form.periodEnd}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, periodEnd: event.target.value }))
                  }
                  required
                />
              </div>
            </div>
            {formError ? (
              <p role="alert" className="mb-2 text-sm font-medium text-destructive">
                {formError}
              </p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreateOpen(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : null}
                Create run
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
