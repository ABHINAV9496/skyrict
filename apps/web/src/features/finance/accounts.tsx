"use client";

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { BookOpen, ChevronRight, LoaderCircle, Plus } from "lucide-react";

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
  createAccount,
  deactivateAccount,
  getTrialBalance,
  listAccounts,
  listFiscalPeriods,
  type Account,
  type AccountType,
  type FiscalPeriod,
  type TrialBalance,
  type TrialBalanceRow,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { ACCOUNT_TYPE_LABELS, formatDate, formatMoney, toMoney } from "@/lib/finance/format";
import { cn } from "@/lib/utils";
import { CODE_RANGE_HINTS } from "@/lib/finance/account-classification";
import { TableToolbar } from "@/features/finance/components/table-toolbar";
import { ActiveBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState, FinanceErrorState } from "@/features/finance/components/state-cards";
import {
  PeriodSelector,
  defaultPeriodValue,
  resolvePeriodRange,
  today,
  type PeriodValue,
} from "@/features/finance/components/period-selector";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; accounts: Account[]; busy: string | null };

const accountSchema = z.object({
  code: z
    .string()
    .trim()
    .min(1, "Code is required")
    .max(32, "Codes are at most 32 characters"),
  name: z
    .string()
    .trim()
    .min(1, "Name is required")
    .max(255, "Names are at most 255 characters"),
  account_type: z.enum(["asset", "liability", "equity", "revenue", "expense"]),
});

type AccountValues = z.infer<typeof accountSchema>;

function CreateAccountDialog({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<AccountValues>({
    resolver: zodResolver(accountSchema),
    defaultValues: { code: "", name: "", account_type: "asset" },
  });

  const accountType = watch("account_type");

  async function onSubmit(values: AccountValues) {
    setSubmitError(null);
    try {
      await createAccount(values);
      setOpen(false);
      reset();
      onCreated();
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "The account could not be created.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus aria-hidden="true" className="size-4" />
          New account
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <BookOpen aria-hidden="true" className="size-5" />
          </div>
          <DialogHeader>
            <DialogTitle>New account</DialogTitle>
            <DialogDescription>
              Add a chart of accounts entry. Codes must be unique within the workspace.
            </DialogDescription>
          </DialogHeader>
        </div>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="account-code">Code</Label>
            <Input
              id="account-code"
              placeholder="e.g. 1000"
              aria-invalid={errors.code ? true : undefined}
              {...register("code")}
            />
            {errors.code ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.code.message}
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Recommended ranges:{" "}
              {CODE_RANGE_HINTS.map(
                (h, i) =>
                  `${h.range} = ${h.label}${i < CODE_RANGE_HINTS.length - 1 ? ", " : ""}`,
              )}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="account-name">Name</Label>
            <Input
              id="account-name"
              placeholder="e.g. Cash and equivalents"
              aria-invalid={errors.name ? true : undefined}
              {...register("name")}
            />
            {errors.name ? (
              <p role="alert" className="text-xs font-medium text-destructive">
                {errors.name.message}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="account-type">Type</Label>
            <Select
              value={accountType}
              onValueChange={(value) => setValue("account_type", value as AccountType)}
            >
              <SelectTrigger id="account-type" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ACCOUNT_TYPE_LABELS) as AccountType[]).map((type) => (
                  <SelectItem key={type} value={type}>
                    {ACCOUNT_TYPE_LABELS[type]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
              Create account
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Standard chart-of-accounts presentation order. */
const COA_ORDER: AccountType[] = ["asset", "liability", "equity", "revenue", "expense"];

/** Natural sort so 1000 < 1010 < 10100 reads like a real chart of accounts. */
function compareCodes(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

/** Asset and expense accounts are debit-normal; liability, equity, and revenue are credit-normal. */
function isDebitNormal(type: AccountType): boolean {
  return type === "asset" || type === "expense";
}

function FinanceAccounts() {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periods, setPeriods] = useState<FiscalPeriod[]>([]);
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());
  const [trialBalance, setTrialBalance] = useState<TrialBalance | null>(null);
  const [asOf, setAsOf] = useState(today());
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [balanceError, setBalanceError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<AccountType>>(new Set());

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [accounts, fetchedPeriods] = await Promise.all([
        listAccounts(true),
        listFiscalPeriods(),
      ]);
      setPeriods(fetchedPeriods);
      setStatus({ state: "ready", accounts, busy: null });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load accounts.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadBalance = useCallback(async () => {
    setBalanceLoading(true);
    setBalanceError(null);
    try {
      const date = resolvePeriodRange(periodValue).asOf;
      setAsOf(date);
      setTrialBalance(await getTrialBalance(date));
    } catch (error) {
      setBalanceError(
        error instanceof ApiError ? error.message : "Could not load account balances.",
      );
      setTrialBalance(null);
    } finally {
      setBalanceLoading(false);
    }
  }, [periodValue]);

  useEffect(() => {
    if (status.state === "ready") void loadBalance();
  }, [status.state, loadBalance]);

  const tbByAccount = useMemo(() => {
    const map = new Map<string, TrialBalanceRow>();
    if (trialBalance) {
      for (const row of trialBalance.rows) map.set(row.account_id, row);
    }
    return map;
  }, [trialBalance]);

  async function onDeactivate(accountId: string) {
    if (status.state !== "ready") return;
    setStatus({ ...status, busy: accountId });
    try {
      await deactivateAccount(accountId);
      await load();
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not deactivate the account.",
      });
    }
  }

  function toggleType(type: AccountType) {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Accounts"
          description="Chart of accounts — the ledger categories the business posts to."
          icon={BookOpen}
        />
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Accounts"
          description="Chart of accounts — the ledger categories the business posts to."
          icon={BookOpen}
        />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  const needle = query.trim().toLowerCase();
  const visibleAccounts = needle
    ? status.accounts.filter(
        (account) =>
          account.code.toLowerCase().includes(needle) ||
          account.name.toLowerCase().includes(needle),
      )
    : status.accounts;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader
          title="Accounts"
          description="Chart of accounts — the ledger categories the business posts to."
          icon={BookOpen}
        />
        <div className="flex flex-wrap items-center gap-2">
          <TableToolbar
            searchPlaceholder="Search code or name…"
            searchValue={query}
            onSearchChange={setQuery}
            period={
              <PeriodSelector
                value={periodValue}
                onChange={setPeriodValue}
                periods={periods}
                label="Balance period"
              />
            }
            actions={canWrite ? <CreateAccountDialog onCreated={() => void load()} /> : null}
          />
        </div>
      </div>

      {status.accounts.length === 0 ? (
        <FinanceEmptyState
          icon={BookOpen}
          title="No accounts yet"
          description="Create your first account to start building the chart of accounts."
        />
      ) : (
        <div className="space-y-6">
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="max-h-[min(70vh,42rem)] overflow-y-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="sticky top-0 z-10 border-b border-border bg-muted">
                    <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Code</th>
                    <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Name</th>
                    <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Normal</th>
                    <th scope="col" className="px-4 py-3 text-right text-xs font-semibold tracking-wider text-muted-foreground uppercase">Balance</th>
                    <th scope="col" className="px-4 py-3 text-xs font-semibold tracking-wider text-muted-foreground uppercase">Status</th>
                    <th scope="col" className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {COA_ORDER.map((type) => {
                    const group = visibleAccounts
                      .filter((account) => account.account_type === type)
                      .sort((a, b) => compareCodes(a.code, b.code));
                    if (group.length === 0) return null;
                    const groupBalance = group.reduce((sum, account) => {
                      const row = tbByAccount.get(account.id);
                      if (!row) return sum;
                      const balance = isDebitNormal(account.account_type)
                        ? toMoney(row.debit) - toMoney(row.credit)
                        : toMoney(row.credit) - toMoney(row.debit);
                      return sum + balance;
                    }, 0);
                    const isCollapsed = collapsed.has(type);
                    return (
                      <Fragment key={type}>
                        <tr className="border-b border-border bg-muted/40">
                          <td colSpan={6} className="px-2 py-1">
                            <button
                              type="button"
                              onClick={() => toggleType(type)}
                              aria-expanded={!isCollapsed}
                              className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted/60"
                            >
                              <ChevronRight
                                aria-hidden="true"
                                className={cn(
                                  "size-4 shrink-0 text-muted-foreground transition-transform",
                                  !isCollapsed && "rotate-90",
                                )}
                              />
                              <span className="font-display text-sm font-semibold text-foreground">
                                {ACCOUNT_TYPE_LABELS[type]}
                              </span>
                              <span className="text-xs font-normal text-muted-foreground">
                                {group.length}
                              </span>
                              <span className="ml-auto pr-2 text-sm font-medium tabular-nums text-foreground">
                                {balanceLoading ? "…" : formatMoney(groupBalance)}
                              </span>
                            </button>
                          </td>
                        </tr>
                        {!isCollapsed
                          ? group.map((account) => (
                              <tr key={account.id} className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/30">
                                <td className="px-4 py-3">
                                  <code className="font-mono text-xs">{account.code}</code>
                                </td>
                                <td className="px-4 py-3 text-foreground">{account.name}</td>
                                <td className="px-4 py-3 text-muted-foreground">
                                  {isDebitNormal(account.account_type) ? "Debit" : "Credit"}
                                </td>
                                <td className="px-4 py-3 text-right tabular-nums text-foreground">
                                  {balanceLoading ? "…" : (() => {
                                    const row = tbByAccount.get(account.id);
                                    if (!row) return "—";
                                    const balance = isDebitNormal(account.account_type)
                                      ? row.debit - row.credit
                                      : row.credit - row.debit;
                                    return formatMoney(balance);
                                  })()}
                                </td>
                                <td className="px-4 py-3">
                                  <ActiveBadge active={account.is_active} />
                                </td>
                                <td className="px-4 py-3 text-right">
                                  {account.is_active && canWrite ? (
                                    <Button
                                      type="button"
                                      variant="ghost"
                                      size="sm"
                                      disabled={status.busy !== null}
                                      onClick={() => void onDeactivate(account.id)}
                                    >
                                      {status.busy === account.id ? (
                                        <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
                                      ) : null}
                                      Deactivate
                                    </Button>
                                  ) : null}
                                </td>
                              </tr>
                            ))
                          : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="border-t border-border/60 bg-muted/20 px-4 py-2.5 text-sm">
              <span className="flex justify-between gap-4">
                <span className="text-muted-foreground">
                  {status.accounts.filter((account) => account.is_active).length} active ·{" "}
                  {status.accounts.length} total · balances as of {formatDate(asOf)}
                </span>
                <span className="tabular-nums text-foreground">
                  {balanceLoading ? "…" : formatMoney(
                    status.accounts.reduce((sum, account) => {
                      const row = tbByAccount.get(account.id);
                      if (!row) return sum;
                      const balance = isDebitNormal(account.account_type)
                        ? toMoney(row.debit) - toMoney(row.credit)
                        : toMoney(row.credit) - toMoney(row.debit);
                      return sum + balance;
                    }, 0),
                  )}
                </span>
              </span>
            </div>
          </div>
          {balanceError ? (
            <p role="alert" className="text-sm font-medium text-destructive">
              {balanceError}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

export { CreateAccountDialog, FinanceAccounts };
