"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useController, useFieldArray, useForm, type Control } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, CircleCheck, LoaderCircle, NotebookPen, Plus, Sparkles, Trash2, TriangleAlert } from "lucide-react";

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
  getDuplicates,
  listAccounts,
  listFiscalPeriods,
  listJournalEntries,
  suggestAccountCode,
  type Account,
  type DuplicateGroup,
  type FiscalPeriod,
  type JournalEntry,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { ACCOUNT_TYPE_LABELS, formatDate, formatMoney, sumMoney } from "@/lib/finance/format";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import {
  PeriodSelector,
  defaultPeriodValue,
  resolvePeriodRange,
  type PeriodValue,
} from "@/features/finance/components/period-selector";
import { EntryStatusBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState, FinanceErrorState } from "@/features/finance/components/state-cards";
import { DuplicatesWidget } from "@/features/finance/components/automation-widgets";
import { cn } from "@/lib/utils";
import { AccountCombobox } from "@/features/finance/components/account-combobox";
import { LineItemsTable, type LineItemColumn } from "@/features/finance/components/line-items-table";
import { TableToolbar } from "@/features/finance/components/table-toolbar";

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

function AccountRow({
  control,
  accounts,
  index,
  errorMessage,
  inputRef,
}: {
  control: Control<EntryValues>;
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

interface CreateJournalEntryDialogProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  initialValues?: { memo: string; accountCode: string; amount: number | null; side: "debit" | "credit" };
}

function CreateJournalEntryDialog({
  open: controlledOpen,
  onOpenChange,
  initialValues,
}: CreateJournalEntryDialogProps = {}) {
  const router = useRouter();
  const [internalOpen, setInternalOpen] = useState(false);
  const open = controlledOpen ?? internalOpen;
  const setOpen = onOpenChange ?? setInternalOpen;
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const accountInputRefs = useRef<(HTMLInputElement | null)[]>([]);
  const initialValuesAppliedRef = useRef(false);

  const [memoSuggestion, setMemoSuggestion] = useState<null | {
    code: string;
    name: string;
    confidence: number;
    reasoning: string;
    accountType?: string;
    amount: number | null;
    side: "debit" | "credit";
  }>(null);
  const [memoSuggestionLoading, setMemoSuggestionLoading] = useState(false);

  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<EntryValues>({
    resolver: zodResolver(entrySchema),
    defaultValues: {
      entry_date: new Date().toISOString().slice(0, 10),
      memo: "",
      lines: [{ account_code: "", debit: "", credit: "" }],
    },
  });

  const memoValue = watch("memo");

  const { fields, append, remove } = useFieldArray({ control, name: "lines" });
  const lines = watch("lines");
  const { debit, credit } = useMemo(() => totals(lines), [lines]);
  const balanced = isBalanced(lines);
  const difference = debit - credit;

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

  useEffect(() => {
    if (!open || !initialValues || initialValuesAppliedRef.current) return;
    if (initialValues.memo) {
      setValue("memo", initialValues.memo);
    }
    if (initialValues.accountCode && fields.length > 0) {
      setValue("lines.0.account_code", initialValues.accountCode);
      if (initialValues.amount != null && initialValues.amount > 0) {
        const amountStr = initialValues.amount.toFixed(2);
        if (initialValues.side === "credit") {
          setValue("lines.0.credit", amountStr);
        } else {
          setValue("lines.0.debit", amountStr);
        }
      }
      initialValuesAppliedRef.current = true;
    }
  }, [open, initialValues, setValue, fields.length]);

  useEffect(() => {
    if (!open) {
      initialValuesAppliedRef.current = false;
      setMemoSuggestion(null);
      setMemoSuggestionLoading(false);
    }
  }, [open]);

  const fetchMemoSuggestion = useCallback(async () => {
    const text = memoValue?.trim();
    if (!text || text.length < 5) {
      setMemoSuggestion(null);
      return;
    }
    setMemoSuggestionLoading(true);
    try {
      const result = await suggestAccountCode(text);
      if (!result.suggested_code) {
        setMemoSuggestion(null);
        return;
      }
      const matched = accounts.find((a) => a.code === result.suggested_code);
      setMemoSuggestion({
        code: result.suggested_code,
        name: result.suggested_name,
        confidence: result.confidence,
        reasoning: result.reasoning,
        accountType: matched?.account_type,
        amount: result.amount,
        side: result.side,
      });
    } catch {
      setMemoSuggestion(null);
    } finally {
      setMemoSuggestionLoading(false);
    }
  }, [memoValue, accounts]);

  useEffect(() => {
    if (!open) return;
    const text = memoValue?.trim() ?? "";
    if (text.length < 5) {
      setMemoSuggestion(null);
      return;
    }
    const timer = setTimeout(() => {
      void fetchMemoSuggestion();
    }, 600);
    return () => clearTimeout(timer);
  }, [memoValue, open, fetchMemoSuggestion]);

  function applyMemoSuggestion() {
    if (!memoSuggestion) return;
    const targetIndex = fields.findIndex((f) => {
      const val = f.account_code;
      return !val || val.trim() === "";
    });
    const idx = targetIndex >= 0 ? targetIndex : 0;
    setValue(`lines.${idx}.account_code`, memoSuggestion.code);
    if (memoSuggestion.amount != null && memoSuggestion.amount > 0) {
      const amountStr = memoSuggestion.amount.toFixed(2);
      if (memoSuggestion.side === "credit") {
        setValue(`lines.${idx}.credit`, amountStr);
      } else {
        setValue(`lines.${idx}.debit`, amountStr);
      }
    }
    setMemoSuggestion(null);
  }

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

  const lineColumns: LineItemColumn[] = [
    { label: "Account" },
    { label: "Debit", align: "right" },
    { label: "Credit", align: "right" },
    { label: "", className: "w-10" },
  ];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      {!controlledOpen && (
        <DialogTrigger asChild>
          <Button>
            <Plus aria-hidden="true" className="size-4" />
            New entry
          </Button>
        </DialogTrigger>
      )}
      <DialogContent className="sm:max-w-3xl">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <NotebookPen aria-hidden="true" className="size-5" />
          </div>
          <DialogHeader>
            <DialogTitle>New journal entry</DialogTitle>
            <DialogDescription>
              A draft entry in the general ledger. Debits and credits must balance and reference
              chart of accounts codes.
            </DialogDescription>
          </DialogHeader>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="max-h-[min(85vh,42rem)] space-y-4 overflow-y-auto pr-1">
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
              <div className="flex gap-2">
                <Input id="entry-memo" placeholder="Optional description" aria-invalid={errors.memo ? true : undefined} className="flex-1" {...register("memo")} />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={memoSuggestionLoading || !memoValue?.trim() || (memoValue?.trim().length ?? 0) < 5}
                  onClick={() => void fetchMemoSuggestion()}
                >
                  {memoSuggestionLoading ? (
                    <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
                  ) : (
                    <Sparkles aria-hidden="true" className="size-3.5" />
                  )}
                  Suggest
                </Button>
              </div>
              {errors.memo ? (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {errors.memo.message}
                </p>
              ) : null}
            </div>
          </div>

          {memoSuggestion ? (
            <div className="flex items-center gap-3 rounded-lg border border-dashed border-primary/40 bg-primary/5 p-3 text-sm">
              <Sparkles aria-hidden="true" className="size-4 shrink-0 text-primary" />
              <span>
                Suggested:{" "}
                <span className="font-mono font-semibold">{memoSuggestion.code}</span>{" "}
                <span className="text-foreground">{memoSuggestion.name}</span>
                {memoSuggestion.accountType ? (
                  <span
                    className={cn(
                      "ml-2 inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium",
                      memoSuggestion.accountType === "expense" &&
                        "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
                      memoSuggestion.accountType === "revenue" &&
                        "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
                      memoSuggestion.accountType === "asset" &&
                        "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
                      memoSuggestion.accountType === "liability" &&
                        "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
                      memoSuggestion.accountType === "equity" &&
                        "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
                    )}
                  >
                    {ACCOUNT_TYPE_LABELS[memoSuggestion.accountType as keyof typeof ACCOUNT_TYPE_LABELS]}
                  </span>
                ) : null}
                {memoSuggestion.amount != null && memoSuggestion.amount > 0 ? (
                  <span className="ml-2 font-mono text-xs tabular-nums text-muted-foreground">
                    {memoSuggestion.side === "credit" ? "Cr" : "Dr"}{" "}
                    {formatMoney(memoSuggestion.amount)}
                  </span>
                ) : null}
                <span className="ml-2 text-xs text-muted-foreground">
                  ({Math.round(memoSuggestion.confidence * 100)}%)
                </span>
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="ml-auto shrink-0"
                onClick={applyMemoSuggestion}
              >
                Apply
              </Button>
            </div>
          ) : null}

          <div className="space-y-2">
            <Label>Lines</Label>
            <LineItemsTable
              columns={lineColumns}
              footer={
                <span className="flex items-center justify-between gap-4">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1.5 text-xs font-medium",
                      balanced
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-amber-600 dark:text-amber-400",
                    )}
                  >
                    {balanced ? (
                      <CircleCheck aria-hidden="true" className="size-3.5" />
                    ) : (
                      <TriangleAlert aria-hidden="true" className="size-3.5" />
                    )}
                    {balanced ? "Balanced" : `Off by ${formatMoney(Math.abs(difference))}`}
                  </span>
                  <span className="tabular-nums text-muted-foreground">
                    Debit {formatMoney(debit)} · Credit {formatMoney(credit)}
                  </span>
                </span>
              }
              onAddRow={() => {
                const nextIndex = fields.length;
                append({ account_code: "", debit: "", credit: "" });
                requestAnimationFrame(() => accountInputRefs.current[nextIndex]?.focus());
              }}
            >
              {fields.map((field, index) => (
                <tr key={field.id} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-1">
                    <AccountRow
                      control={control}
                      accounts={accounts}
                      index={index}
                      errorMessage={errors.lines?.[index]?.account_code?.message}
                      inputRef={(el) => {
                        accountInputRefs.current[index] = el;
                      }}
                    />
                  </td>
                  <td className="w-28 px-3 py-1">
                    <Input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      placeholder="0.00"
                      aria-invalid={errors.lines?.[index]?.debit ? true : undefined}
                      {...register(`lines.${index}.debit`)}
                    />
                    {errors.lines?.[index]?.debit ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.debit?.message}
                      </p>
                    ) : null}
                  </td>
                  <td className="w-28 px-3 py-1">
                    <Input
                      type="number"
                      inputMode="decimal"
                      min="0"
                      step="0.01"
                      placeholder="0.00"
                      aria-invalid={errors.lines?.[index]?.credit ? true : undefined}
                      {...register(`lines.${index}.credit`)}
                    />
                    {errors.lines?.[index]?.credit ? (
                      <p role="alert" className="text-xs font-medium text-destructive">
                        {errors.lines[index]?.credit?.message}
                      </p>
                    ) : null}
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
              ))}
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

function FinanceJournalEntries() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());
  const [query, setQuery] = useState("");
  const [statusTab, setStatusTab] = useState<string>("all");
  const [duplicates, setDuplicates] = useState<DuplicateGroup[]>([]);
  const [duplicatesLoading, setDuplicatesLoading] = useState(true);
  const [duplicatesError, setDuplicatesError] = useState<string | null>(null);

  const [draftOpen, setDraftOpen] = useState(false);
  const [draftInitialValues, setDraftInitialValues] = useState<
    { memo: string; accountCode: string; amount: number | null; side: "debit" | "credit" } | undefined
  >(undefined);
  const paramsAppliedRef = useRef(false);

  useEffect(() => {
    const draftMemo = searchParams.get("draft_memo");
    const draftAccount = searchParams.get("draft_account");
    if (draftMemo && draftAccount && !paramsAppliedRef.current) {
      paramsAppliedRef.current = true;
      const draftAmountStr = searchParams.get("draft_amount");
      const draftAmount = draftAmountStr ? Number(draftAmountStr) : null;
      const draftSide = searchParams.get("draft_side");
      setDraftInitialValues({
        memo: draftMemo,
        accountCode: draftAccount,
        amount: Number.isFinite(draftAmount) && (draftAmount as number) > 0 ? draftAmount : null,
        side: draftSide === "credit" ? "credit" : "debit",
      });
      setDraftOpen(true);
      const params = new URLSearchParams(searchParams.toString());
      params.delete("draft_memo");
      params.delete("draft_account");
      params.delete("draft_amount");
      params.delete("draft_side");
      const qs = params.toString();
      router.replace(`/dashboard/erp/finance/journal-entries${qs ? `?${qs}` : ""}`, { scroll: false });
    }
  }, [searchParams, router]);

  const loadDuplicates = useCallback(async () => {
    setDuplicatesLoading(true);
    setDuplicatesError(null);
    try {
      setDuplicates(await getDuplicates());
    } catch (error) {
      setDuplicatesError(
        error instanceof ApiError ? error.message : "Could not load duplicate suggestions.",
      );
    } finally {
      setDuplicatesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDuplicates();
  }, [loadDuplicates]);

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
      <div className="space-y-4">
        <PageHeader
          title="Journal Entries"
          description="The general ledger — every debit and credit the business posts."
          icon={NotebookPen}
        />
        <TableToolbar
          searchPlaceholder="Search memo or date…"
          searchValue={query}
          onSearchChange={setQuery}
          tabs={[
            { key: "all", label: "All", count: status.entries.length },
            { key: "draft", label: "Draft", count: status.entries.filter((e) => e.status === "draft").length },
            { key: "posted", label: "Posted", count: status.entries.filter((e) => e.status === "posted").length },
            { key: "voided", label: "Voided", count: status.entries.filter((e) => e.status === "voided").length },
          ]}
          activeTab={statusTab}
          onTabChange={setStatusTab}
          period={
            <PeriodSelector
              value={periodValue}
              onChange={setPeriodValue}
              periods={periods}
              label="Entry period"
            />
          }
          actions={canWrite ? <CreateJournalEntryDialog open={draftOpen} onOpenChange={setDraftOpen} initialValues={draftInitialValues} /> : null}
        />
      </div>

      <div className="rounded-xl border border-border bg-card p-4">
        <DuplicatesWidget
          groups={duplicates}
          loading={duplicatesLoading}
          error={duplicatesError}
          onRetry={() => void loadDuplicates()}
        />
      </div>

      {(() => {
        const needle = query.trim().toLowerCase();
        const visibleEntries = status.entries.filter((entry) => {
          if (statusTab !== "all" && entry.status !== statusTab) return false;
          if (!needle) return true;
          return (
            (entry.memo ?? "").toLowerCase().includes(needle) ||
            entry.entry_date.toLowerCase().includes(needle)
          );
        });
        return visibleEntries.length === 0 ? (
        <FinanceEmptyState
          icon={NotebookPen}
          title="No journal entries yet"
          description="Create a draft entry with balanced lines to start the ledger."
        />
      ) : (
        <FinanceTable
          columns={columns}
          rows={visibleEntries}
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
        );
      })()}
    </div>
  );
}

export { CreateJournalEntryDialog, FinanceJournalEntries };
