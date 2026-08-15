"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, LoaderCircle, NotebookPen, Plus, Trash2 } from "lucide-react";

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
  createJournalEntry,
  listFiscalPeriods,
  listJournalEntries,
  type FiscalPeriod,
  type JournalEntry,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney, sumMoney } from "@/lib/finance/format";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import {
  PeriodSelector,
  defaultPeriodValue,
  resolvePeriodRange,
  type PeriodValue,
} from "@/features/finance/components/period-selector";
import { EntryStatusBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState, FinanceErrorState } from "@/features/finance/components/state-cards";
import { cn } from "@/lib/utils";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; entries: JournalEntry[] };

const lineSchema = z
  .object({
    account_code: z.string().trim().min(1, "Account code is required"),
    debit: z.string().trim(),
    credit: z.string().trim(),
  })
  .refine((line) => {
    const debit = toAmount(line.debit);
    const credit = toAmount(line.credit);
    return (Number.isFinite(debit) && debit > 0) || (Number.isFinite(credit) && credit > 0);
  }, { message: "Enter a positive debit or credit", path: ["debit"] });

const entrySchema = z.object({
  entry_date: z.string().min(1, "Entry date is required"),
  memo: z.string().trim().max(500, "Memo is at most 500 characters"),
  lines: z.array(lineSchema).min(1, "Add at least one line"),
});

type LineValues = z.infer<typeof lineSchema>;
type EntryValues = z.infer<typeof entrySchema>;

function toAmount(value: string): number {
  const trimmed = value.trim();
  if (trimmed === "") return 0;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : 0;
}

function totals(lines: LineValues[]): { debit: number; credit: number } {
  return lines.reduce(
    (acc, line) => ({
      debit: acc.debit + toAmount(line.debit),
      credit: acc.credit + toAmount(line.credit),
    }),
    { debit: 0, credit: 0 },
  );
}

function isBalanced(lines: LineValues[]): boolean {
  const { debit, credit } = totals(lines);
  return Math.abs(debit - credit) < 0.005;
}

function CreateJournalEntryDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<EntryValues>({
    resolver: zodResolver(entrySchema),
    defaultValues: {
      entry_date: new Date().toISOString().slice(0, 10),
      memo: "",
      lines: [{ account_code: "", debit: "", credit: "" }],
    },
  });

  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lines = watch("lines");
  const { debit, credit } = useMemo(() => totals(lines), [lines]);
  const balanced = isBalanced(lines);

  async function onSubmit(values: EntryValues) {
    if (!balanced) {
      setSubmitError("Debits and credits must balance before posting.");
      return;
    }
    setSubmitError(null);
    try {
      const entry = await createJournalEntry({
        entry_date: values.entry_date,
        memo: values.memo || undefined,
        lines: values.lines.map((line) => {
          const debitAmount = toAmount(line.debit);
          const creditAmount = toAmount(line.credit);
          return {
            account_code: line.account_code.trim(),
            debit: debitAmount > 0 ? debitAmount : undefined,
            credit: creditAmount > 0 ? creditAmount : undefined,
          };
        }),
      });
      setOpen(false);
      reset();
      router.push(`/dashboard/erp/finance/journal-entries/${entry.id}`);
    } catch (error) {
      setSubmitError(
        error instanceof ApiError ? error.message : "The journal entry could not be created.",
      );
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden="true" className="size-4" />
          New entry
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>New journal entry</DialogTitle>
          <DialogDescription>
            A draft entry in the general ledger. Debits and credits must balance and reference
            chart of accounts codes.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="entry-date">Entry date</Label>
              <Input id="entry-date" type="date" aria-invalid={errors.entry_date ? true : undefined} {...register("entry_date")} />
              {errors.entry_date ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.entry_date.message}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="entry-memo">Memo</Label>
              <Input id="entry-memo" placeholder="Optional description" aria-invalid={errors.memo ? true : undefined} {...register("memo")} />
              {errors.memo ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.memo.message}
                </p>
              ) : null}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Lines</Label>
              <span className="text-xs text-muted-foreground tabular-nums">
                Debit {formatMoney(debit)} · Credit {formatMoney(credit)}
              </span>
            </div>
            <div className="space-y-2">
              {fields.map((field, index) => (
                <div key={field.id} className="flex items-start gap-2">
                  <div className="min-w-0 flex-1 space-y-1.5">
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
                  <div className="w-28 space-y-1.5">
                    <Input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      placeholder="Debit"
                      aria-invalid={errors.lines?.[index]?.debit ? true : undefined}
                      {...register(`lines.${index}.debit`)}
                    />
                    {errors.lines?.[index]?.debit ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.debit?.message}
                      </p>
                    ) : null}
                  </div>
                  <div className="w-28 space-y-1.5">
                    <Input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      placeholder="Credit"
                      aria-invalid={errors.lines?.[index]?.credit ? true : undefined}
                      {...register(`lines.${index}.credit`)}
                    />
                    {errors.lines?.[index]?.credit ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.credit?.message}
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
            <Button type="button" variant="outline" size="sm" onClick={() => append({ account_code: "", debit: "", credit: "" })}>
              <Plus aria-hidden="true" className="size-3.5" />
              Add line
            </Button>
            {errors.lines?.message ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.lines.message}
              </p>
            ) : null}
            {!balanced ? (
              <p
                role="alert"
                className={cn(
                  "text-xs font-medium",
                  errors.lines?.root ? "text-destructive" : "text-amber-600 dark:text-amber-400",
                )}
              >
                Total debits must equal total credits.
              </p>
            ) : null}
          </div>

          {submitError ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {submitError}
            </p>
          ) : null}

          <DialogFooter>
            <Button type="submit" disabled={isSubmitting || !balanced}>
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

const columns: FinanceColumn<JournalEntry>[] = [
  { label: "Date", render: (entry) => formatDate(entry.entry_date) },
  { label: "Memo", render: (entry) => entry.memo ?? "—" },
  { label: "Status", render: (entry) => <EntryStatusBadge status={entry.status} /> },
  {
    label: "Debit",
    align: "right",
    render: (entry) => (
      <span className="tabular-nums">
        {formatMoney(sumMoney(entry.lines.map((line) => line.debit)))}
      </span>
    ),
  },
  {
    label: "Credit",
    align: "right",
    render: (entry) => (
      <span className="tabular-nums">
        {formatMoney(sumMoney(entry.lines.map((line) => line.credit)))}
      </span>
    ),
  },
  {
    label: "Lines",
    align: "right",
    render: (entry) => <span className="tabular-nums">{entry.lines.length}</span>,
  },
  {
    label: "",
    align: "right",
    render: (entry) => (
      <Link
        href={`/dashboard/erp/finance/journal-entries/${entry.id}`}
        className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
      >
        View <ArrowRight aria-hidden="true" className="size-3.5" />
      </Link>
    ),
  },
];

export function FinanceJournalEntries() {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const range = resolvePeriodRange(periodValue);
      const [entries, fetchedPeriods] = await Promise.all([
        listJournalEntries({
          limit: 50,
          from_date: range.from ?? undefined,
          to_date: range.to ?? undefined,
        }),
        listFiscalPeriods(),
      ]);
      setPeriods(fetchedPeriods);
      setStatus({ state: "ready", entries: entries.data });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load journal entries.",
      });
    }
  }, [periodValue]);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Journal Entries"
          description="The general ledger — every debit and credit the business posts."
          icon={NotebookPen}
        />
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Journal Entries"
          description="The general ledger — every debit and credit the business posts."
          icon={NotebookPen}
        />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader
          title="Journal Entries"
          description="The general ledger — every debit and credit the business posts."
          icon={NotebookPen}
        />
        <div className="flex flex-wrap items-center gap-2">
          <PeriodSelector
            value={periodValue}
            onChange={setPeriodValue}
            periods={periods}
            label="Entry period"
          />
          {canWrite ? <CreateJournalEntryDialog /> : null}
        </div>
      </div>

      {status.entries.length === 0 ? (
        <FinanceEmptyState
          icon={NotebookPen}
          title="No journal entries yet"
          description="Create a draft entry with balanced lines to start the ledger."
        />
      ) : (
        <FinanceTable
          columns={columns}
          rows={status.entries}
          getKey={(entry) => entry.id}
          footer={
            <span className="flex justify-between gap-4">
              <span>
                {periodValue.granularity === "all"
                  ? `${status.entries.length} entries shown (latest 50)`
                  : `${status.entries.length} entries in the selected period`}
              </span>
              <span className="tabular-nums">
                {formatMoney(
                  sumMoney(
                    status.entries.flatMap((entry) => entry.lines.map((line) => line.debit)),
                  ),
                )}{" "}
                /{" "}
                {formatMoney(
                  sumMoney(
                    status.entries.flatMap((entry) => entry.lines.map((line) => line.credit)),
                  ),
                )}
              </span>
            </span>
          }
        />
      )}
    </div>
  );
}
