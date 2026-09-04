"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  BadgeCheck,
  Calculator,
  CircleX,
  LoaderCircle,
  Receipt,
  SlidersHorizontal,
  UserRound,
  Zap,
} from "lucide-react";

import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
import { Badge } from "@/components/ui/badge";
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
import { Checkbox } from "@/components/ui/checkbox";
import { useModuleAccess } from "@/lib/access/modules";
import {
  approvePayrollRun,
  computePayrollRun,
  getPayrollRun,
  getRunPayslips,
  listRunEntries,
  markPayrollRunPaid,
  updateRunEntry,
  voidPayrollRun,
  type PayrollEntry,
  type PayrollRun,
  type Payslip,
  type SkippedEmployee,
} from "@/lib/api/payroll-api";
import {
  enqueuePayrollBatch,
  type PayrollBatch,
} from "@/lib/api/payroll-automation-api";
import { listEmployees, type Employee } from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; run: PayrollRun; entries: PayrollEntry[] };

type Notice = { tone: "success" | "error"; text: string };

type ConfirmAction = "approve" | "pay" | "void" | null;

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium tabular-nums text-foreground">{value}</span>
    </div>
  );
}

function PreflightSummary({ preflight }: { preflight: Record<string, unknown> }) {
  const checks = (preflight.checks ?? {}) as Record<string, { status?: string; detail?: string }>;
  const blocks = (preflight.blocks ?? []) as string[];
  const warnings = (preflight.warnings ?? []) as string[];
  const rosterCount = typeof preflight.roster_count === "number" ? preflight.roster_count : null;

  const entries = Object.entries(checks).map(([key, check]) => ({
    key,
    status: check.status ?? "warn",
    detail: check.detail ?? "",
  }));

  return (
    <div className="space-y-3 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>Pre-flight check</span>
        {rosterCount != null ? <span>· {rosterCount} employee(s)</span> : null}
        {preflight.checked_at ? (
          <span>· {formatDateTime(String(preflight.checked_at))}</span>
        ) : null}
      </div>
      {entries.length > 0 ? (
        <ul className="space-y-1.5">
          {entries.map((entry) => (
            <li key={entry.key} className="flex items-start gap-2 text-sm">
              <StatusPip status={entry.status} />
              <span className="min-w-0">
                <span className="font-medium text-foreground">{entry.key}</span>
                {entry.detail ? (
                  <span className="ml-1.5 text-muted-foreground">— {entry.detail}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {warnings.length > 0 ? (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          {warnings.length} warning(s) — not blocking.
        </p>
      ) : null}
      {blocks.length > 0 ? (
        <p className="text-xs font-medium text-destructive">
          {blocks.length} blocking issue(s): {blocks.join(", ")}.
        </p>
      ) : null}
    </div>
  );
}

function StatusPip({ status }: { status: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "mt-1.5 size-2 shrink-0 rounded-full",
        status === "ok"
          ? "bg-emerald-500"
          : status === "block"
            ? "bg-destructive"
            : "bg-amber-500",
      )}
    />
  );
}

export function RunDetailClient({ runId }: { runId: string }) {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.payroll.write");
  const canApprove =
    permissions.includes("*") || permissions.includes("erp.payroll.approve");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [payslips, setPayslips] = useState<Payslip[]>([]);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null);
  const [voidReason, setVoidReason] = useState("");
  const [adjustEntry, setAdjustEntry] = useState<PayrollEntry | null>(null);
  const [adjustAmount, setAdjustAmount] = useState("");
  const [adjustSaving, setAdjustSaving] = useState(false);
  const [adjustError, setAdjustError] = useState<string | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchDryRun, setBatchDryRun] = useState(true);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchResult, setBatchResult] = useState<PayrollBatch | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [run, entries, employeeList, payslipList] = await Promise.all([
        getPayrollRun(runId),
        listRunEntries(runId),
        listEmployees({ pageSize: 100 }),
        getRunPayslips(runId).catch(() => [] as Payslip[]),
      ]);
      setEmployees(employeeList.items);
      setPayslips(payslipList);
      setStatus({ state: "ready", run, entries });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load this payroll run.";
      setStatus({ state: "error", message });
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const employeeName = useMemo(() => {
    const byId = new Map(employees.map((employee) => [employee.id, `${employee.firstName} ${employee.lastName}`]));
    return (id: string) => byId.get(id) ?? null;
  }, [employees]);

  async function runAction(action: Exclude<ConfirmAction, null>) {
    if (!status.state || busy) return;
    if (action === "void" && !voidReason.trim()) {
      setNotice({ tone: "error", text: "A reason is required to void a run." });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      let updated: PayrollRun;
      if (action === "approve") updated = await approvePayrollRun(runId);
      else if (action === "pay") updated = await markPayrollRunPaid(runId);
      else updated = await voidPayrollRun(runId);
      setStatus((current) =>
        current.state === "ready" ? { ...current, run: updated } : current,
      );
      setNotice({ tone: "success", text: `Run marked as ${updated.status}.` });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "The action failed.",
      });
    } finally {
      setBusy(false);
      setConfirmAction(null);
      setVoidReason("");
    }
  }

  async function onCompute() {
    if (!status.state || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await computePayrollRun(runId);
      setPayslips(await getRunPayslips(runId).catch(() => []));
      setStatus({
        state: "ready",
        run: result.run,
        entries: result.entries,
      });
      setNotice({
        tone: "success",
        text:
          result.skipped.length > 0
            ? `Run computed - ${result.skipped.length} employee(s) skipped.`
            : "Run computed.",
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not compute the run.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onAdjust() {
    if (status.state !== "ready" || !adjustEntry || adjustSaving) return;
    const amount = adjustAmount.trim();
    if (!/^-?\d+(\.\d+)?$/.test(amount)) {
      setAdjustError("Enter a numeric adjustment amount.");
      return;
    }
    const delta = Number(amount);
    const snapshot = status.entries;
    setAdjustSaving(true);
    setAdjustError(null);
    setNotice(null);
    setStatus({
      state: "ready",
      run: status.run,
      entries: status.entries.map((entry) =>
        entry.id === adjustEntry.id
          ? {
              ...entry,
              adjustments: { ...(entry.adjustments ?? {}), amount },
              net: {
                amount: String(Math.round((Number(entry.net.amount) - delta) * 100) / 100),
                currency: entry.net.currency,
              },
            }
          : entry,
      ),
    });
    try {
      const updated = await updateRunEntry(runId, adjustEntry.id, { amount });
      setStatus((current) =>
        current.state === "ready"
          ? {
              ...current,
              entries: current.entries.map((entry) =>
                entry.id === updated.id ? updated : entry,
              ),
            }
          : current,
      );
      setNotice({ tone: "success", text: "Entry adjusted." });
      setAdjustEntry(null);
      setAdjustAmount("");
    } catch (error) {
      setStatus({ state: "ready", run: status.run, entries: snapshot });
      setAdjustError(
        error instanceof ApiError ? error.message : "Could not adjust this entry.",
      );
    } finally {
      setAdjustSaving(false);
    }
  }

  if (status.state === "loading") {
    return <ErpDataTableSkeleton columns={5} />;
  }

  if (status.state === "error" || !status.state) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
        <p className="text-sm font-medium text-destructive">
          {status.state === "error" ? status.message : "Payroll run not found."}
        </p>
        <Button asChild variant="outline" size="sm" className="mt-3">
          <Link href="/dashboard/erp/payroll/runs">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to runs
          </Link>
        </Button>
      </div>
    );
  }

  const { run, entries } = status;

  const canCompute = canWrite && run.status === "draft";
  const canApproveRun = canApprove && run.status === "computed";
  const canPay = canApprove && run.status === "approved";
  const canVoid = canApprove && (run.status === "computed" || run.status === "approved");
  const canAdjust = canWrite && (run.status === "draft" || run.status === "computed");
  const canBatch = canWrite && run.status === "computed";

  async function onSubmitBatch() {
    if (!status.state || batchSubmitting) return;
    setBatchSubmitting(true);
    setNotice(null);
    try {
      const batch = await enqueuePayrollBatch({ runId, dryRun: batchDryRun });
      setBatchResult(batch);
      setNotice({
        tone: "success",
        text: `Batch ${batch.batchId ? `#${batch.batchId} ` : ""}${batch.dryRun ? "dry-run " : ""}enqueued.`,
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError ? error.message : "Could not submit the batch.",
      });
    } finally {
      setBatchSubmitting(false);
    }
  }

  const columns: ErpColumn<PayrollEntry>[] = [
    {
      key: "employeeId",
      label: "Employee",
      render: (entry) => (
        <span className="font-medium text-foreground">
          {employeeName(entry.employeeId) ?? entry.employeeId}
        </span>
      ),
    },
    {
      key: "baseSalary",
      label: "Base salary",
      align: "right",
      render: (entry) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(entry.baseSalary.amount, entry.baseSalary.currency)}
        </span>
      ),
    },
    {
      key: "payDays",
      label: "Days",
      align: "right",
      render: (entry) => (
        <span className="tabular-nums text-muted-foreground">{entry.payDays}</span>
      ),
    },
    {
      key: "gross",
      label: "Gross",
      align: "right",
      render: (entry) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(entry.gross.amount, entry.gross.currency)}
        </span>
      ),
    },
    {
      key: "deductions",
      label: "Deductions",
      align: "right",
      render: (entry) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(entry.deductions.amount, entry.deductions.currency)}
        </span>
      ),
    },
    {
      key: "net",
      label: "Net",
      align: "right",
      render: (entry) => (
        <span className="tabular-nums font-medium text-foreground">
          {formatMoney(entry.net.amount, entry.net.currency)}
        </span>
      ),
    },
    ...(canAdjust
      ? [
          {
            key: "id" as const,
            label: "",
            align: "right" as const,
            render: (entry: PayrollEntry) => (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={(event) => {
                  event.stopPropagation();
                  setAdjustAmount(
                    entry.adjustments?.amount != null ? String(entry.adjustments.amount) : "",
                  );
                  setAdjustError(null);
                  setAdjustEntry(entry);
                }}
              >
                <SlidersHorizontal aria-hidden="true" className="size-3.5" />
                Adjust
              </Button>
            ),
          },
        ]
      : []),
  ];

  const confirmMeta: Record<
    Exclude<ConfirmAction, null>,
    { title: string; description: string; button: string; destructive: boolean }
  > = {
    approve: {
      title: "Approve this run?",
      description: "Approval locks the numbers in. The run can still be voided before payment.",
      button: "Approve run",
      destructive: false,
    },
    pay: {
      title: "Mark as paid?",
      description: "This records payment for every entry in the run. It can't be undone.",
      button: "Mark paid",
      destructive: false,
    },
    void: {
      title: "Void this run?",
      description: "Voiding discards the run. Provide a reason so the audit trail stays clear.",
      button: "Void run",
      destructive: true,
    },
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
          <Link href="/dashboard/erp/payroll/runs">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Payroll runs
          </Link>
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-xl font-semibold tracking-tight text-foreground">
              {run.runCode}
            </h1>
            <StatusBadge status={run.status} />
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">
            {formatDate(run.periodStart)} → {formatDate(run.periodEnd)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canCompute ? (
            <Button type="button" disabled={busy} onClick={() => void onCompute()}>
              {busy ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <Calculator aria-hidden="true" className="size-4" />
              )}
              Compute
            </Button>
          ) : null}
          {canBatch ? (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                setBatchResult(null);
                setBatchDryRun(true);
                setBatchOpen(true);
              }}
            >
              <Zap aria-hidden="true" className="size-4" />
              Run automation batch
            </Button>
          ) : null}
          {canApproveRun ? (
            <Button
              type="button"
              disabled={busy}
              onClick={() => setConfirmAction("approve")}
            >
              <BadgeCheck aria-hidden="true" className="size-4" />
              Approve
            </Button>
          ) : null}
          {canPay ? (
            <Button
              type="button"
              disabled={busy}
              onClick={() => setConfirmAction("pay")}
            >
              <Receipt aria-hidden="true" className="size-4" />
              Mark paid
            </Button>
          ) : null}
          {canVoid ? (
            <Button
              type="button"
              variant="outline"
              className="text-destructive hover:text-destructive"
              disabled={busy}
              onClick={() => setConfirmAction("void")}
            >
              <CircleX aria-hidden="true" className="size-4" />
              Void
            </Button>
          ) : null}
        </div>
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

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground">
          <Receipt aria-hidden="true" className="size-4 text-primary" />
          Summary
        </h2>
        <div className="mt-3 divide-y divide-border">
          <SummaryRow label="Employees in run" value={entries.length} />
          <SummaryRow
            label="Total gross"
            value={run.totalGross ? formatMoney(run.totalGross.amount, run.totalGross.currency) : "-"}
          />
          <SummaryRow
            label="Total net"
            value={run.totalNet ? formatMoney(run.totalNet.amount, run.totalNet.currency) : "-"}
          />
          {run.computedAt ? (
            <SummaryRow label="Computed" value={formatDateTime(run.computedAt)} />
          ) : null}
          {run.approvedAt ? (
            <SummaryRow label="Approved" value={formatDateTime(run.approvedAt)} />
          ) : null}
          {run.paidAt ? (
            <SummaryRow label="Paid" value={formatDateTime(run.paidAt)} />
          ) : null}
          {run.paidAt ? (
            <SummaryRow
              label="Accrual JE"
              value={
                run.jeBridgeStatus === "draft" ? (
                  <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
                    Journal entry draft
                  </Badge>
                ) : run.jeBridgeStatus === "pending" ? (
                  <Badge variant="secondary" className="bg-amber-500/10 text-amber-700 dark:text-amber-300">
                    Pending accounts setup
                  </Badge>
                ) : (
                  <span className="text-muted-foreground">Not created</span>
                )
              }
            />
          ) : null}
          {run.voidReason ? (
            <SummaryRow label="Void reason" value={run.voidReason} />
          ) : null}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground">
          <UserRound aria-hidden="true" className="size-4 text-primary" />
          Entries
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            Read-only after approval
          </span>
        </h2>
        <div className="mt-4">
          {entries.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No entries yet. Compute the run to generate pay lines.
            </p>
          ) : (
            <ErpDataTable
              columns={columns}
              rows={entries}
              meta={{ total: entries.length, page: 1, page_size: entries.length, total_pages: 1 }}
            />
          )}
        </div>
      </section>

      {payslips.length > 0 ? (
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground">
            <Receipt aria-hidden="true" className="size-4 text-primary" />
            Payslips
            <span className="ml-auto text-xs font-normal text-muted-foreground">
              Per-employee net pay after deduction
            </span>
          </h2>
          <div className="mt-4">
            <ErpDataTable
              columns={[
                {
                  key: "employeeId",
                  label: "Employee",
                  render: (payslip) => (
                    <span className="font-medium text-foreground">
                      {payslip.employeeName}
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        {payslip.employeeNumber}
                      </span>
                    </span>
                  ),
                },
                {
                  key: "gross",
                  label: "Gross",
                  align: "right",
                  render: (payslip) => (
                    <span className="tabular-nums text-muted-foreground">
                      {formatMoney(payslip.gross.amount, payslip.gross.currency)}
                    </span>
                  ),
                },
                {
                  key: "deductions",
                  label: "Deductions",
                  align: "right",
                  render: (payslip) => (
                    <span className="tabular-nums text-muted-foreground">
                      {formatMoney(payslip.deductions.amount, payslip.deductions.currency)}
                    </span>
                  ),
                },
                {
                  key: "net",
                  label: "Net",
                  align: "right",
                  render: (payslip) => (
                    <span className="tabular-nums font-medium text-foreground">
                      {formatMoney(payslip.net.amount, payslip.net.currency)}
                    </span>
                  ),
                },
              ]}
              rows={payslips.map((payslip) => ({ ...payslip, id: payslip.employeeId }))}
              meta={{
                total: payslips.length,
                page: 1,
                page_size: payslips.length,
                total_pages: 1,
              }}
            />
          </div>
        </section>
      ) : null}

      {run.skippedEmployees.length > 0 ? (
        <section className="rounded-xl border border-border bg-card p-5">
          <h2 className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground">
            <CircleX aria-hidden="true" className="size-4 text-primary" />
            Skipped employees
          </h2>
          <div className="mt-3 divide-y divide-border">
            {run.skippedEmployees.map((skipped: SkippedEmployee) => (
              <div
                key={skipped.employeeId}
                className="flex items-center justify-between gap-4 py-2"
              >
                <span className="text-sm font-medium text-foreground">
                  {employeeName(skipped.employeeId) ?? skipped.employeeId}
                </span>
                <span className="text-sm text-muted-foreground">{skipped.reason}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <Dialog
        open={confirmAction !== null}
        onOpenChange={(open) => !busy && !open && setConfirmAction(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{confirmAction ? confirmMeta[confirmAction].title : ""}</DialogTitle>
            <DialogDescription>
              {confirmAction ? confirmMeta[confirmAction].description : ""}
            </DialogDescription>
          </DialogHeader>
          {confirmAction === "void" ? (
            <div className="space-y-1.5 py-4">
              <Label htmlFor="void-reason">Reason</Label>
              <Input
                id="void-reason"
                value={voidReason}
                onChange={(event) => setVoidReason(event.target.value)}
                placeholder="e.g. Wrong pay period"
                required
              />
            </div>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmAction(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={confirmAction && confirmMeta[confirmAction].destructive ? "destructive" : "default"}
              disabled={busy}
              onClick={() => confirmAction && void runAction(confirmAction)}
            >
              {busy ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              {confirmAction ? confirmMeta[confirmAction].button : ""}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={adjustEntry !== null}
        onOpenChange={(open) => !adjustSaving && !open && setAdjustEntry(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Adjust entry</DialogTitle>
            <DialogDescription>
              Apply a flat adjustment to this entry. Positive amounts reduce net
              pay; negative amounts increase it.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5 py-4">
            <Label htmlFor="adjust-amount">Adjustment amount</Label>
            <Input
              id="adjust-amount"
              type="number"
              step="0.01"
              value={adjustAmount}
              onChange={(event) => setAdjustAmount(event.target.value)}
              placeholder="e.g. 200 or -50"
            />
            {adjustError ? (
              <p className="text-xs font-medium text-destructive">{adjustError}</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAdjustEntry(null)}
              disabled={adjustSaving}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void onAdjust()} disabled={adjustSaving}>
              {adjustSaving ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Save adjustment
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={batchOpen} onOpenChange={(open) => !batchSubmitting && !open && setBatchOpen(false)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Run automation batch</DialogTitle>
            <DialogDescription>
              Submit this run to the payroll automation worker. A pre-flight pass
              reports blocking issues; the dry-run toggle processes the roster
              without persisting payslips.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-3">
            {batchResult ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={batchResult.status} />
                  {batchResult.dryRun ? (
                    <Badge variant="secondary">Dry run</Badge>
                  ) : null}
                  <span className="text-xs text-muted-foreground">
                    {batchResult.batchId ? `Batch #${batchResult.batchId}` : "Batch"}
                  </span>
                </div>
                {Object.keys(batchResult.totals).length > 0 ? (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {(["total", "done", "failed", "retried", "skipped"] as const).map((key) =>
                      batchResult.totals[key] != null ? (
                        <div key={key} className="rounded-lg border border-border bg-muted/30 p-2">
                          <p className="text-xs text-muted-foreground">{key}</p>
                          <p className="text-base font-semibold tabular-nums">
                            {String(batchResult.totals[key])}
                          </p>
                        </div>
                      ) : null,
                    )}
                  </div>
                ) : null}
                {batchResult.preflight ? (
                  <PreflightSummary preflight={batchResult.preflight} />
                ) : null}
              </div>
            ) : (
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={batchDryRun}
                  onCheckedChange={(value) => setBatchDryRun(value === true)}
                />
                Dry run (no payslips persisted)
              </label>
            )}
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setBatchOpen(false)}
              disabled={batchSubmitting}
            >
              {batchResult ? "Done" : "Cancel"}
            </Button>
            {!batchResult ? (
              <Button
                type="button"
                onClick={() => void onSubmitBatch()}
                disabled={batchSubmitting}
              >
                {batchSubmitting ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : (
                  <Zap aria-hidden="true" className="size-4" />
                )}
                {batchSubmitting ? "Submitting…" : batchDryRun ? "Start dry run" : "Submit batch"}
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
