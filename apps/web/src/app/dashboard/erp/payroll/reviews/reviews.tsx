"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  CircleX,
  Download,
  LoaderCircle,
  ReceiptText,
  Stamp,
} from "lucide-react";

import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
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
import { useModuleAccess } from "@/lib/access/modules";
import {
  approvePayslipReview,
  downloadPayslipPdf,
  listPayslipReviews,
  rejectPayslipReview,
  type PayslipReview,
  type PayslipReviewStatus,
} from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type Filter = PayslipReviewStatus | "all";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; reviews: PayslipReview[] };

type Notice = { tone: "success" | "error"; text: string };

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "draft", label: "Awaiting approval" },
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
];

export function PayslipReviewsClient({ runId }: { runId?: string }) {
  const { permissions } = useModuleAccess();
  const canApprove =
    permissions.includes("*") || permissions.includes("erp.payroll.approve");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [filter, setFilter] = useState<Filter>("draft");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [rejectTarget, setRejectTarget] = useState<PayslipReview | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectSaving, setRejectSaving] = useState(false);
  const [rejectError, setRejectError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const reviews = await listPayslipReviews(runId ? { runId } : {});
      setStatus({ state: "ready", reviews });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load payslip reviews.";
      setStatus({ state: "error", message });
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const rows = useMemo(() => {
    if (status.state !== "ready") return [];
    return filter === "all"
      ? status.reviews
      : status.reviews.filter((review) => review.status === filter);
  }, [status, filter]);

  async function onApprove(review: PayslipReview) {
    if (!canApprove || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const updated = await approvePayslipReview(review.id);
      setStatus((current) =>
        current.state === "ready"
          ? {
              state: "ready",
              reviews: current.reviews.map((row) =>
                row.id === updated.id ? updated : row,
              ),
            }
          : current,
      );
      setNotice({ tone: "success", text: `${review.employeeName} approved — payslip delivered.` });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not approve this payslip.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function onReject() {
    if (!rejectTarget || rejectSaving) return;
    const reason = rejectReason.trim();
    if (!reason) {
      setRejectError("A reason is required to reject a payslip.");
      return;
    }
    setRejectSaving(true);
    setRejectError(null);
    setNotice(null);
    const target = rejectTarget;
    try {
      const updated = await rejectPayslipReview(target.id, reason);
      setStatus((current) =>
        current.state === "ready"
          ? {
              state: "ready",
              reviews: current.reviews.map((row) =>
                row.id === updated.id ? updated : row,
              ),
            }
          : current,
      );
      setNotice({ tone: "success", text: `${target.employeeName} rejected.` });
      setRejectTarget(null);
      setRejectReason("");
    } catch (error) {
      setRejectError(
        error instanceof ApiError ? error.message : "Could not reject this payslip.",
      );
    } finally {
      setRejectSaving(false);
    }
  }

  async function onDownload(review: PayslipReview) {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    try {
      await downloadPayslipPdf(review.id);
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not download the payslip PDF.",
      });
    } finally {
      setBusy(false);
    }
  }

  if (status.state === "loading") {
    return <ErpDataTableSkeleton columns={6} />;
  }

  if (status.state === "error" || !status.state) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
        <p className="text-sm font-medium text-destructive">
          {status.state === "error" ? status.message : "Payslip reviews not found."}
        </p>
      </div>
    );
  }

  const draftCount = status.reviews.filter((review) => review.status === "draft").length;

  const columns: ErpColumn<PayslipReview>[] = [
    {
      key: "employeeId",
      label: "Employee",
      render: (review) => (
        <span className="font-medium text-foreground">
          {review.employeeName}
          <span className="ml-1.5 text-xs font-normal text-muted-foreground">
            {review.employeeNumber}
          </span>
        </span>
      ),
    },
    {
      key: "version",
      label: "Version",
      align: "right",
      render: (review) => (
        <span className="tabular-nums text-muted-foreground">{review.version}</span>
      ),
    },
    {
      key: "gross",
      label: "Gross",
      align: "right",
      render: (review) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(review.gross.amount, review.gross.currency)}
        </span>
      ),
    },
    {
      key: "deductions",
      label: "Deductions",
      align: "right",
      render: (review) => (
        <span className="tabular-nums text-muted-foreground">
          {formatMoney(review.deductions.amount, review.deductions.currency)}
        </span>
      ),
    },
    {
      key: "net",
      label: "Net",
      align: "right",
      render: (review) => (
        <span className="tabular-nums font-medium text-foreground">
          {formatMoney(review.net.amount, review.net.currency)}
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (review) => {
        if (review.status === "draft") {
          return (
            <Badge variant="secondary" className="bg-amber-500/10 text-amber-700 dark:text-amber-300">
              Awaiting approval
            </Badge>
          );
        }
        if (review.status === "rejected") {
          return (
            <Badge variant="secondary" className="bg-rose-500/10 text-rose-700 dark:text-rose-300">
              Rejected
            </Badge>
          );
        }
        return (
          <Badge variant="secondary" className="bg-emerald-500/10 text-emerald-700 dark:text-emerald-300">
            Approved
          </Badge>
        );
      },
    },
    ...(canApprove
      ? [
          {
            key: "id" as const,
            label: "",
            align: "right" as const,
            render: (review: PayslipReview) => (
              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  onClick={(event) => {
                    event.stopPropagation();
                    void onDownload(review);
                  }}
                >
                  <Download aria-hidden="true" className="size-3.5" />
                  PDF
                </Button>
                {review.status === "draft" ? (
                  <>
                    <Button
                      type="button"
                      variant="default"
                      size="sm"
                      disabled={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        void onApprove(review);
                      }}
                    >
                      <BadgeCheck aria-hidden="true" className="size-3.5" />
                      Approve
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      disabled={busy}
                      onClick={(event) => {
                        event.stopPropagation();
                        setRejectError(null);
                        setRejectTarget(review);
                        setRejectReason("");
                      }}
                    >
                      <CircleX aria-hidden="true" className="size-3.5" />
                      Reject
                    </Button>
                  </>
                ) : null}
              </div>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 font-display text-xl font-semibold tracking-tight text-foreground">
            <Stamp aria-hidden="true" className="size-5 text-primary" />
            Payslip approvals
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Approval releases each payslip to its employee. Rejected slips are
            recommitted and re-approved as a new version.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1 rounded-lg bg-muted p-1">
          {FILTERS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setFilter(item.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                filter === item.key
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
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

      {draftCount > 0 && filter !== "all" ? (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">
          <CircleX aria-hidden="true" className="size-4" />
          {draftCount} payslip(s) awaiting approval.
        </div>
      ) : null}

      <section className="rounded-xl border border-border bg-card p-5">
        <h2 className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground">
          <ReceiptText aria-hidden="true" className="size-4 text-primary" />
          Review queue
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {rows.length} of {status.reviews.length} payslips
          </span>
        </h2>
        <div className="mt-4">
          {rows.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center">
              <p className="text-sm text-muted-foreground">No payslips in this state.</p>
            </div>
          ) : (
            <ErpDataTable
              columns={columns}
              rows={rows}
              meta={{
                total: rows.length,
                page: 1,
                page_size: rows.length,
                total_pages: 1,
              }}
            />
          )}
        </div>
      </section>

      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(open) => !rejectSaving && !open && setRejectTarget(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Reject payslip</DialogTitle>
            <DialogDescription>
              {rejectTarget
                ? `${rejectTarget.employeeName} (v${rejectTarget.version}) won't be delivered. Explain why so the correction is clear.`
                : ""}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5 py-4">
            <Label htmlFor="reject-reason">Reason</Label>
            <Input
              id="reject-reason"
              value={rejectReason}
              onChange={(event) => setRejectReason(event.target.value)}
              placeholder="e.g. Wrong base pay — hours not applied"
              required
            />
            {rejectError ? (
              <p className="text-xs font-medium text-destructive">{rejectError}</p>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRejectTarget(null)}
              disabled={rejectSaving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void onReject()}
              disabled={rejectSaving}
            >
              {rejectSaving ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Reject payslip
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}