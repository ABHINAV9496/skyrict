"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useController, useFieldArray, useForm, type Control } from "react-hook-form";
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
  listAccounts,
  listFiscalPeriods,
  listInvoices,
  type Account,
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
  today,
  type PeriodValue,
} from "@/features/finance/components/period-selector";
import { InvoiceStatusBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState, FinanceErrorState } from "@/features/finance/components/state-cards";
import { AccountCombobox } from "@/features/finance/components/account-combobox";
import { LineItemsTable, type LineItemColumn } from "@/features/finance/components/line-items-table";
import { TableToolbar } from "@/features/finance/components/table-toolbar";

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

function InvoiceAccountRow({
  control,
  accounts,
  index,
  errorMessage,
  inputRef,
}: {
  control: Control<InvoiceValues>;
  accounts: Account[];
  index: number;
  errorMessage?: string;
  inputRef?: (el: HTMLInputElement | null) => void;
}) {
  const { field } = useController({
    control,
    name: `lines.${index}.account_code`,
  });
  return (
    <>
      <AccountCombobox
        accounts={accounts}
        value={field.value}
        onChange={field.onChange}
        invalid={Boolean(errorMessage)}
        inputRef={inputRef}
      />
      {errorMessage ? (
        <p role="alert" className="text-xs font-medium text-destructive">
          {errorMessage}
        </p>
      ) : null}
    </>
  );
}

function CreateInvoiceDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const accountInputRefs = useRef<(HTMLInputElement | null)[]>([]);

  const {
    register,
    handleSubmit,
    control,
    watch,
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
  const lines = watch("lines");
  const subtotal = useMemo(
    () =>
      lines.reduce((sum, line) => {
        const quantity = Number(line.quantity);
        const price = Number(line.unit_price);
        return sum + (Number.isFinite(quantity) && Number.isFinite(price) ? quantity * price : 0);
      }, 0),
    [lines],
  );

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void listAccounts(true)
      .then((fetched) => {
        if (!cancelled) setAccounts(fetched);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [open]);

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

  const lineColumns: LineItemColumn[] = [
    { label: "Description" },
    { label: "Account" },
    { label: "Qty", align: "right", className: "w-20" },
    { label: "Unit price", align: "right", className: "w-28" },
    { label: "Amount", align: "right", className: "w-28" },
    { label: "", className: "w-10" },
  ];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden="true" className="size-4" />
          New invoice
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <ReceiptText aria-hidden="true" className="size-5" />
          </div>
          <DialogHeader>
            <DialogTitle>New invoice</DialogTitle>
            <DialogDescription>
              A draft manual invoice. Lines post to the revenue account codes you choose.
            </DialogDescription>
          </DialogHeader>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="max-h-[min(85vh,42rem)] space-y-4 overflow-y-auto pr-1">
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
            <LineItemsTable
              columns={lineColumns}
              footer={
                <span className="flex items-center justify-between gap-4">
                  <span className="text-xs font-medium text-muted-foreground">Subtotal</span>
                  <span className="tabular-nums text-foreground">{formatMoney(subtotal)}</span>
                </span>
              }
              onAddRow={() => {
                const nextIndex = fields.length;
                append({ description: "", account_code: "", quantity: "1", unit_price: "" });
                requestAnimationFrame(() => accountInputRefs.current[nextIndex]?.focus());
              }}
            >
              {fields.map((field, index) => {
                const quantity = Number(watch(`lines.${index}.quantity`) ?? "");
                const price = Number(watch(`lines.${index}.unit_price`) ?? "");
                const amount =
                  Number.isFinite(quantity) && Number.isFinite(price) ? quantity * price : 0;
                return (
                  <tr key={field.id} className="border-b border-border/60 last:border-0">
                    <td className="px-3 py-1">
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
                    </td>
                    <td className="px-3 py-1">
                      <InvoiceAccountRow
                        control={control}
                        accounts={accounts}
                        index={index}
                        errorMessage={errors.lines?.[index]?.account_code?.message}
                        inputRef={(el) => {
                          accountInputRefs.current[index] = el;
                        }}
                      />
                    </td>
                    <td className="px-3 py-1 text-right">
                      <Input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="1"
                        placeholder="1"
                        className="ml-auto text-right"
                        aria-invalid={errors.lines?.[index]?.quantity ? true : undefined}
                        {...register(`lines.${index}.quantity`)}
                      />
                      {errors.lines?.[index]?.quantity ? (
                        <p role="alert" className="text-xs font-medium text-destructive">
                          {errors.lines[index]?.quantity?.message}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-3 py-1 text-right">
                      <Input
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        placeholder="0.00"
                        className="ml-auto text-right"
                        aria-invalid={errors.lines?.[index]?.unit_price ? true : undefined}
                        {...register(`lines.${index}.unit_price`)}
                      />
                      {errors.lines?.[index]?.unit_price ? (
                        <p role="alert" className="text-xs font-medium text-destructive">
                          {errors.lines[index]?.unit_price?.message}
                        </p>
                      ) : null}
                    </td>
                    <td className="px-3 py-1 text-right tabular-nums text-muted-foreground">
                      {formatMoney(amount)}
                    </td>
                    <td className="px-3 py-1 text-right">
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
                    </td>
                  </tr>
                );
              })}
            </LineItemsTable>
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
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
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

function FinanceInvoices() {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());
  const [query, setQuery] = useState("");
  const [statusTab, setStatusTab] = useState<string>("all");

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
  const isOpen = (invoice: Invoice) => invoice.status !== "paid" && invoice.status !== "voided";
  const openInvoices = visibleInvoices.filter(isOpen);
  const overdueInvoices = openInvoices.filter((invoice) => invoice.due_date < today());

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <PageHeader
          title="Invoices"
          description="Bill customers and track each invoice through issue, approval, and payment."
          icon={ReceiptText}
        />
        <TableToolbar
          searchPlaceholder="Search invoice number…"
          searchValue={query}
          onSearchChange={setQuery}
          tabs={[
            { key: "all", label: "All", count: visibleInvoices.length },
            { key: "open", label: "Open", count: openInvoices.length },
            { key: "paid", label: "Paid", count: visibleInvoices.filter((i) => i.status === "paid").length },
            { key: "overdue", label: "Overdue", count: overdueInvoices.length },
          ]}
          activeTab={statusTab}
          onTabChange={setStatusTab}
          period={
            <PeriodSelector
              value={periodValue}
              onChange={setPeriodValue}
              periods={periods}
              label="Invoice period"
            />
          }
          actions={canWrite ? <CreateInvoiceDialog /> : null}
        />
      </div>

      {status.invoices.length === 0 ? (
        <FinanceEmptyState
          icon={ReceiptText}
          title="No invoices yet"
          description="Create a draft invoice to start billing customers."
        />
      ) : (
        <FinanceTable
          columns={columns}
          rows={visibleInvoices.filter((invoice) => {
            if (statusTab === "open" && !isOpen(invoice)) return false;
            if (statusTab === "paid" && invoice.status !== "paid") return false;
            if (statusTab === "overdue" && !overdueInvoices.includes(invoice)) return false;
            if (query.trim()) {
              const needle = query.trim().toLowerCase();
              if (!invoice.invoice_number.toLowerCase().includes(needle)) return false;
            }
            return true;
          })}
          getKey={(invoice) => invoice.id}
          footer={`${visibleInvoices.length} invoices in the selected period`}
        />
      )}
    </div>
  );
}

export { CreateInvoiceDialog, FinanceInvoices };
