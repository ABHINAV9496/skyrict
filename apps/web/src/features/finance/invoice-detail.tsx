"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Banknote, LoaderCircle, ReceiptText } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
  applyPayment,
  approveInvoice,
  getInvoice,
  issueInvoice,
  listAccounts,
  voidInvoice,
  type Account,
  type Invoice,
  type Payment,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatDateTime, formatMoney } from "@/lib/finance/format";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import { InvoiceStatusBadge } from "@/features/finance/components/status-badge";
import { FinanceErrorState } from "@/features/finance/components/state-cards";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; invoice: Invoice; accounts: Account[]; busy: string | null };

const paymentSchema = z.object({
  amount: z.string().trim().min(1, "Amount is required"),
  method: z.string().trim().min(1, "Method is required").max(32, "Method is at most 32 characters"),
  paid_at: z.string().min(1, "Payment date is required"),
});

type PaymentValues = z.infer<typeof paymentSchema>;

function ApplyPaymentDialog({
  invoice,
  onApplied,
}: {
  invoice: Invoice;
  onApplied: (payment: Payment) => void;
}) {
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PaymentValues>({
    resolver: zodResolver(paymentSchema),
    defaultValues: {
      amount: String(invoice.total),
      method: "",
      paid_at: new Date().toISOString().slice(0, 16),
    },
  });

  async function onSubmit(values: PaymentValues) {
    setSubmitError(null);
    try {
      const payment = await applyPayment(invoice.id, {
        amount: Number(values.amount),
        method: values.method.trim(),
        paid_at: new Date(values.paid_at).toISOString(),
      });
      setOpen(false);
      reset();
      onApplied(payment);
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "The payment could not be applied.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Banknote aria-hidden="true" className="size-4" />
          Apply payment
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Apply payment</DialogTitle>
          <DialogDescription>
            Record a cash receipt against invoice {invoice.invoice_number}. Marking it paid closes
            the invoice.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="payment-amount">Amount</Label>
            <Input
              id="payment-amount"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              aria-invalid={errors.amount ? true : undefined}
              {...register("amount")}
            />
            {errors.amount ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.amount.message}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="payment-method">Method</Label>
            <Input
              id="payment-method"
              placeholder="e.g. Bank transfer"
              aria-invalid={errors.method ? true : undefined}
              {...register("method")}
            />
            {errors.method ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.method.message}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="payment-date">Paid at</Label>
            <Input id="payment-date" type="datetime-local" aria-invalid={errors.paid_at ? true : undefined} {...register("paid_at")} />
            {errors.paid_at ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.paid_at.message}
              </p>
            ) : null}
          </div>
          {submitError ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {submitError}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <Banknote aria-hidden="true" className="size-4" />
              )}
              Apply payment
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function InvoiceDetail({ invoiceId }: { invoiceId: string }) {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const canApprove = hasPermission(permissions, "erp.finance.approve");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [lastPayment, setLastPayment] = useState<Payment | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [invoice, accounts] = await Promise.all([getInvoice(invoiceId), listAccounts(true)]);
      setStatus({ state: "ready", invoice, accounts, busy: null });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the invoice.",
      });
    }
  }, [invoiceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const accountById = useMemo(() => {
    const map = new Map<string, Account>();
    if (status.state === "ready") {
      for (const account of status.accounts) map.set(account.id, account);
    }
    return map;
  }, [status]);

  async function runAction(action: "issue" | "approve" | "void") {
    if (status.state !== "ready" || status.busy !== null) return;
    if (
      action === "void" &&
      !window.confirm("Void this invoice? This cannot be undone.")
    ) {
      return;
    }
    setActionError(null);
    setStatus({ ...status, busy: action });
    try {
      if (action === "issue") await issueInvoice(invoiceId);
      else if (action === "approve") await approveInvoice(invoiceId);
      else await voidInvoice(invoiceId);
      await load();
    } catch (error) {
      setActionError(
        error instanceof ApiError ? error.message : "The action could not be completed.",
      );
      setStatus({ ...status, busy: null });
    }
  }

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader title="Invoice" description="Billing detail." icon={ReceiptText} />
        <TableSkeleton rows={5} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader title="Invoice" description="Billing detail." icon={ReceiptText} />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  const { invoice } = status;
  const canIssue = invoice.status === "draft" && canWrite;
  const canApproveInvoice = invoice.status === "issued" && canApprove;
  const canVoid = (invoice.status === "draft" || invoice.status === "issued") && canWrite;
  const canApplyPayment = invoice.status === "approved" && canWrite;

  const columns: FinanceColumn<Invoice["lines"][number]>[] = [
    { label: "Line", render: (line) => <span className="tabular-nums">{line.line_no}</span> },
    { label: "Description", render: (line) => line.description },
    {
      label: "Account",
      render: (line) => {
        const account = accountById.get(line.account_id);
        return account ? `${account.code} · ${account.name}` : "Unknown account";
      },
    },
    { label: "Qty", align: "right", render: (line) => <span className="tabular-nums">{line.quantity}</span> },
    { label: "Unit", align: "right", render: (line) => formatMoney(line.unit_price) },
    { label: "Amount", align: "right", render: (line) => formatMoney(line.amount) },
  ];

  return (
    <div className="space-y-6">
      <Link
        href="/dashboard/erp/finance/invoices"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Invoices
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader
          title={invoice.invoice_number}
          description={`Customer ${invoice.customer_id}`}
          icon={ReceiptText}
        />
        <div className="flex flex-wrap items-center gap-2">
          <InvoiceStatusBadge status={invoice.status} />
          {canIssue ? (
            <Button type="button" disabled={status.busy !== null} onClick={() => void runAction("issue")}>
              {status.busy === "issue" ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Issue
            </Button>
          ) : null}
          {canApproveInvoice ? (
            <Button type="button" disabled={status.busy !== null} onClick={() => void runAction("approve")}>
              {status.busy === "approve" ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Approve
            </Button>
          ) : null}
          {canApplyPayment ? (
            <ApplyPaymentDialog
              invoice={invoice}
              onApplied={(payment) => {
                setLastPayment(payment);
                void load();
              }}
            />
          ) : null}
          {canVoid ? (
            <Button type="button" variant="outline" disabled={status.busy !== null} onClick={() => void runAction("void")}>
              {status.busy === "void" ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Void
            </Button>
          ) : null}
        </div>
      </div>

      {actionError ? (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
          {actionError}
        </p>
      ) : null}

      {lastPayment ? (
        <div className="rounded-xl border border-primary/30 bg-primary/5 p-4">
          <p className="text-sm font-medium text-foreground">
            Payment {lastPayment.payment_number} applied — {formatMoney(lastPayment.amount)} via{" "}
            {lastPayment.method} on {formatDateTime(lastPayment.paid_at)}.
          </p>
        </div>
      ) : null}

      <dl className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Invoice date</dt>
          <dd className="mt-1 text-sm font-medium text-foreground">{formatDate(invoice.invoice_date)}</dd>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Due date</dt>
          <dd className="mt-1 text-sm font-medium text-foreground">{formatDate(invoice.due_date)}</dd>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Total</dt>
          <dd className="mt-1 text-sm font-medium text-foreground">{formatMoney(invoice.total)}</dd>
        </div>
      </dl>

      <FinanceTable
        columns={columns}
        rows={invoice.lines}
        getKey={(line) => line.id}
        footer={
          <span className="flex justify-between gap-4">
            <span>Total</span>
            <span className="tabular-nums">{formatMoney(invoice.total)}</span>
          </span>
        }
      />
    </div>
  );
}
