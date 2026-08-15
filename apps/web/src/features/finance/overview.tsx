"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Wallet } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { StatCardSkeleton } from "@/components/ui/page-skeletons";
import {
  getProfitAndLoss,
  listAccounts,
  listFiscalPeriods,
  listInvoices,
  listJournalEntries,
  type Account,
  type FiscalPeriod,
  type Invoice,
  type JournalEntry,
  type ProfitAndLoss,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney, sumMoney } from "@/lib/finance/format";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import {
  PeriodSelector,
  defaultPeriodValue,
  resolvePeriodRange,
  today,
  type PeriodValue,
} from "@/features/finance/components/period-selector";
import { EntryStatusBadge, InvoiceStatusBadge } from "@/features/finance/components/status-badge";
import { KpiCard } from "@/features/finance/components/kpi-card";
import { FinanceErrorState } from "@/features/finance/components/state-cards";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      accounts: Account[];
      entries: JournalEntry[];
      invoices: Invoice[];
      periods: FiscalPeriod[];
      pnl: ProfitAndLoss;
    };

const entryColumns: FinanceColumn<JournalEntry>[] = [
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

const invoiceColumns: FinanceColumn<Invoice>[] = [
  { label: "Number", render: (invoice) => invoice.invoice_number },
  { label: "Date", render: (invoice) => formatDate(invoice.invoice_date) },
  { label: "Status", render: (invoice) => <InvoiceStatusBadge status={invoice.status} /> },
  {
    label: "Total",
    align: "right",
    render: (invoice) => formatMoney(invoice.total),
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

export function FinanceOverview() {
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [periodValue, setPeriodValue] = useState<PeriodValue>(defaultPeriodValue());

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const range = resolvePeriodRange(periodValue);
      const [accounts, entries, invoices, periods] = await Promise.all([
        listAccounts(),
        listJournalEntries({
          limit: 5,
          from_date: range.from ?? undefined,
          to_date: range.to ?? undefined,
        }),
        listInvoices({ limit: 200 }),
        listFiscalPeriods(),
      ]);
      const pnlFrom =
        range.from ??
        (periods.length > 0 ? [...periods].map((period) => period.start_date).sort()[0] : today());
      const pnlTo = range.to ?? today();
      const pnl = await getProfitAndLoss(pnlFrom, pnlTo);
      setStatus({
        state: "ready",
        accounts,
        entries: entries.data,
        invoices: invoices.data,
        periods,
        pnl,
      });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load finance data.",
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
          title="Finance"
          description="Cash, ledgers, invoices, and accounting."
          icon={Wallet}
        />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
        </div>
        <TableSkeleton rows={5} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Finance"
          description="Cash, ledgers, invoices, and accounting."
          icon={Wallet}
        />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  const activeAccounts = status.accounts.filter((account) => account.is_active).length;
  const openPeriods = status.periods.filter((period) => !period.is_closed).length;
  const range = resolvePeriodRange(periodValue);
  const visibleInvoices = status.invoices.filter((invoice) => {
    if (range.from && invoice.invoice_date < range.from) return false;
    if (range.to && invoice.invoice_date > range.to) return false;
    return true;
  });
  const unpaidInvoices = visibleInvoices.filter(
    (invoice) => invoice.status !== "paid" && invoice.status !== "voided",
  );
  const outstanding = sumMoney(unpaidInvoices.map((invoice) => invoice.total));
  const maxAmount = Math.max(status.pnl.total_revenue, status.pnl.total_expenses, 1);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader
          title="Finance"
          description="Cash, ledgers, invoices, and accounting."
          icon={Wallet}
        />
        <PeriodSelector
          value={periodValue}
          onChange={setPeriodValue}
          periods={status.periods}
          label="Overview period"
        />
      </div>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Net income" value={formatMoney(status.pnl.net_income)} hint="Selected period" />
        <KpiCard
          label="Revenue"
          value={formatMoney(status.pnl.total_revenue)}
          hint={`${status.entries.length} journal entries`}
        />
        <KpiCard
          label="Expenses"
          value={formatMoney(status.pnl.total_expenses)}
          hint={`${visibleInvoices.length} invoices`}
        />
        <KpiCard
          label="Outstanding invoices"
          value={formatMoney(outstanding)}
          hint={`${unpaidInvoices.length} unpaid`}
        />
      </section>

      <section className="space-y-4 rounded-xl border border-border bg-card p-5">
        <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
          Revenue vs expenses
        </h2>
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex justify-between text-sm">
              <span className="text-muted-foreground">Revenue</span>
              <span className="font-medium tabular-nums text-foreground">
                {formatMoney(status.pnl.total_revenue)}
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary"
                style={{ width: `${Math.max((status.pnl.total_revenue / maxAmount) * 100, 2)}%` }}
              />
            </div>
          </div>
          <div>
            <div className="mb-1 flex justify-between text-sm">
              <span className="text-muted-foreground">Expenses</span>
              <span className="font-medium tabular-nums text-foreground">
                {formatMoney(status.pnl.total_expenses)}
              </span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-destructive"
                style={{ width: `${Math.max((status.pnl.total_expenses / maxAmount) * 100, 2)}%` }}
              />
            </div>
          </div>
        </div>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
            Recent journal entries
          </h2>
          <Link
            href="/dashboard/erp/finance/journal-entries"
            className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            All entries <ArrowRight aria-hidden="true" className="size-3.5" />
          </Link>
        </div>
        <FinanceTable
          columns={entryColumns}
          rows={status.entries}
          getKey={(entry) => entry.id}
          emptyMessage="No journal entries yet."
        />
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
            Recent invoices
          </h2>
          <Link
            href="/dashboard/erp/finance/invoices"
            className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
          >
            All invoices <ArrowRight aria-hidden="true" className="size-3.5" />
          </Link>
        </div>
        <FinanceTable
          columns={invoiceColumns}
          rows={visibleInvoices}
          getKey={(invoice) => invoice.id}
          emptyMessage="No invoices yet."
        />
      </section>

      <p className="text-sm text-muted-foreground">
        {activeAccounts} active accounts · {status.accounts.length} total · {openPeriods} open fiscal
        periods
      </p>
    </div>
  );
}
