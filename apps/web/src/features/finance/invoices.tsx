"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, LoaderCircle, Plus, ReceiptText, Trash2 } from "lucide-react";

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
  createInvoice,
  listFiscalPeriods,
  listInvoices,
  type FiscalPeriod,
  type Invoice,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/finance/format";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import {
  PeriodSelector,
  defaultPeriodValue,
  resolvePeriodRange,
  type PeriodValue,
} from "@/features/finance/components/period-selector";
import { InvoiceStatusBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState, FinanceErrorState } from "@/features/finance/components/state-cards";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; invoices: Invoice[] };

const invoiceLineSchema = z.object({
  description: z.string().trim().min(1, "Description is required").max(500, "Max 500 characters"),
  account_code: z.string().trim().min(1, "Account code is required"),
  quantity: z.string().trim().min(1, "Quantity is required"),
  unit_price: z.string().trim().min(1, "Unit price is required"),
});

const invoiceSchema = z.object({
  customer_id: z
    .string()
    .trim()
    .min(1, "Customer ID is required")
    .regex(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      "Enter a valid customer UUID",
    ),
  invoice_date: z.string().min(1, "Invoice date is required"),
  due_date: z.string().min(1, "Due date is required"),
  lines: z.array(invoiceLineSchema).min(1, "Add at least one line"),
});

type InvoiceValues = z.infer<typeof invoiceSchema>;

function CreateInvoiceDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<InvoiceValues>({
    resolver: zodResolver(invoiceSchema),
    defaultValues: {
      customer_id: "",
      invoice_date: new Date().toISOString().slice(0, 10),
      due_date: new Date().toISOString().slice(0, 10),
      lines: [{ description: "", account_code: "", quantity: "1", unit_price: "" }],
    },
  });

  const { fields, append, remove } = useFieldArray({ control, name: "lines" });

  async function onSubmit(values: InvoiceValues) {
    if (values.due_date < values.invoice_date) {
      setSubmitError("The due date must be on or after the invoice date.");
      return;
    }
    setSubmitError(null);
    try {
      const invoice = await createInvoice({
        customer_id: values.customer_id.trim(),
        invoice_date: values.invoice_date,
        due_date: values.due_date,
        lines: values.lines.map((line) => ({
          description: line.description.trim(),
          account_code: line.account_code.trim(),
          quantity: Number(line.quantity),
          unit_price: Number(line.unit_price),
        })),
      });
      setOpen(false);
      reset();
      router.push(`/dashboard/erp/finance/invoices/${invoice.id}`);
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "The invoice could not be created.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden="true" className="size-4" />
          New invoice
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New invoice</DialogTitle>
          <DialogDescription>
            A draft manual invoice. Lines post to the revenue account codes you choose.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="space-y-1.5 sm:col-span-3">
              <Label htmlFor="invoice-customer">Customer ID</Label>
              <Input
                id="invoice-customer"
                placeholder="00000000-0000-0000-0000-000000000000"
                aria-invalid={errors.customer_id ? true : undefined}
                {...register("customer_id")}
              />
              {errors.customer_id ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.customer_id.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invoice-date">Invoice date</Label>
              <Input id="invoice-date" type="date" aria-invalid={errors.invoice_date ? true : undefined} {...register("invoice_date")} />
              {errors.invoice_date ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.invoice_date.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="invoice-due">Due date</Label>
              <Input id="invoice-due" type="date" aria-invalid={errors.due_date ? true : undefined} {...register("due_date")} />
              {errors.due_date ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.due_date.message}
                </p>
              ) : null}
            </div>
            <div className="hidden sm:block" />
          </div>

          <div className="space-y-2">
            <Label>Lines</Label>
            <div className="space-y-2">
              {fields.map((field, index) => (
                <div key={field.id} className="flex items-start gap-2">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Input
                      placeholder="Description"
                      aria-invalid={errors.lines?.[index]?.description ? true : undefined}
                      {...register(`lines.${index}.description`)}
                    />
                    {errors.lines?.[index]?.description ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.description?.message}
                      </p>
                    ) : null}
                  </div>
                  <div className="w-36 space-y-1.5">
                    <Input
                      placeholder="Account code"
                      aria-invalid={errors.lines?.[index]?.account_code ? true : undefined}
                      {...register(`lines.${index}.account_code`)}
                    />
                    {errors.lines?.[index]?.account_code ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.account_code?.message}
                      </p>
                    ) : null}
                  </div>
                  <div className="w-24 space-y-1.5">
                    <Input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="1"
                      placeholder="Qty"
                      aria-invalid={errors.lines?.[index]?.quantity ? true : undefined}
                      {...register(`lines.${index}.quantity`)}
                    />
                    {errors.lines?.[index]?.quantity ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.quantity?.message}
                      </p>
                    ) : null}
                  </div>
                  <div className="w-28 space-y-1.5">
                    <Input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      placeholder="Price"
                      aria-invalid={errors.lines?.[index]?.unit_price ? true : undefined}
                      {...register(`lines.${index}.unit_price`)}
                    />
                    {errors.lines?.[index]?.unit_price ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.unit_price?.message}
                      </p>
                    ) : null}
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Remove line"
                    disabled={fields.length === 1}
                    onClick={() => remove(index)}
                  >
                    <Trash2 aria-hidden="true" className="size-3.5" />
                  </Button>
                </div>
              ))}
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => append({ description: "", account_code: "", quantity: "1", unit_price: "" })}>
              <Plus aria-hidden="true" className="size-3.5" />
              Add line
            </Button>
            {errors.lines?.message ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.lines.message}
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
                <Plus aria-hidden="true" className="size-4" />
              )}
              Save draft
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const columns: FinanceColumn<Invoice>[] = [
  { label: "Number", render: (invoice) => invoice.invoice_number },
  { label: "Date", render: (invoice) => formatDate(invoice.invoice_date) },
  { label: "Due", render: (invoice) => formatDate(invoice.due_date) },
  { label: "Status", render: (invoice) => <InvoiceStatusBadge status={invoice.status} /> },
  { label: "Total", align: "right", render: (invoice) => formatMoney(invoice.total) },
  {
    label: "Balance",
    align: "right",
    render: (invoice) => {
      if (invoice.status === "voided") return "—";
      if (invoice.status === "paid") return <span className="tabular-nums">{formatMoney(0)}</span>;
      return <span className="tabular-nums">{formatMoney(invoice.total)}</span>;
    },
  },
  {
    label: "",
    align: "right",
    render: (invoice) => (
      <Link
        href={`/dashboard/erp/finance/invoices/${invoice.id}`}
        className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
      >
        View <ArrowRight aria-hidden="true" className="size-3.5" />
      </Link>
    ),
  },
];

export function FinanceInvoices() {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [invoices, fetchedPeriods] = await Promise.all([
        listInvoices({ limit: 200 }),
        listFiscalPeriods(),
      ]);
      setPeriods(fetchedPeriods);
      setStatus({ state: "ready", invoices: invoices.data });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load invoices.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Invoices"
          description="Bill customers and track each invoice through issue, approval, and payment."
          icon={ReceiptText}
        />
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Invoices"
          description="Bill customers and track each invoice through issue, approval, and payment."
          icon={ReceiptText}
        />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  const range = resolvePeriodRange(periodValue);
  const visibleInvoices = status.invoices.filter((invoice) => {
    if (range.from && invoice.invoice_date < range.from) return false;
    if (range.to && invoice.invoice_date > range.to) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader
          title="Invoices"
          description="Bill customers and track each invoice through issue, approval, and payment."
          icon={ReceiptText}
        />
        <div className="flex flex-wrap items-center gap-2">
          <PeriodSelector
            value={periodValue}
            onChange={setPeriodValue}
            periods={periods}
            label="Invoice period"
          />
          {canWrite ? <CreateInvoiceDialog /> : null}
        </div>
      </div>

      {visibleInvoices.length === 0 ? (
        <FinanceEmptyState
          icon={ReceiptText}
          title={status.invoices.length === 0 ? "No invoices yet" : "No invoices in this period"}
          description={
            status.invoices.length === 0
              ? "Create a draft invoice to start billing customers."
              : "Try a different period — no invoices fall within the selected range."
          }
        />
      ) : (
        <FinanceTable
          columns={columns}
          rows={visibleInvoices}
          getKey={(invoice) => invoice.id}
          footer={`${visibleInvoices.length} invoices in the selected period`}
        />
      )}
    </div>
  );
}
