"use client";

import { useCallback, useEffect, useState } from "react";
import { BarChart3, LoaderCircle } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import {
    getBalanceSheet,
    getProfitAndLoss,
    getTrialBalance,
    listFiscalPeriods,
    type BalanceSheet,
    type FiscalPeriod,
    type ProfitAndLoss,
    type TrialBalance,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import {
    ACCOUNT_TYPE_LABELS,
    formatMoney,
    toMoney,
} from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import {
    PeriodSelector,
    defaultPeriodValue,
    resolvePeriodRange,
    type PeriodValue,
} from "@/features/finance/components/period-selector";
import { FinanceErrorState } from "@/features/finance/components/state-cards";
import { cn } from "@/lib/utils";

type ReportKey = "trial-balance" | "profit-and-loss" | "balance-sheet";

const REPORT_TABS: { key: ReportKey; label: string }[] = [
    { key: "trial-balance", label: "Trial Balance" },
    { key: "profit-and-loss", label: "Profit & Loss" },
    { key: "balance-sheet", label: "Balance Sheet" },
];

function today(): string {
    return new Date().toISOString().slice(0, 10);
}

function firstOfMonth(): string {
    return `${today().slice(0, 8)}01`;
}

function errorMessage(error: unknown, fallback: string): string {
    return error instanceof ApiError ? error.message : fallback;
}

function ReportToolbar({
    fields,
    onRun,
    running,
}: {
    fields: {
        id: string;
        label: string;
        value: string;
        onChange: (value: string) => void;
    }[];
    onRun: () => void;
    running: boolean;
}) {
    return (
        <div className="flex flex-wrap items-end gap-3">
            {fields.map((field) => (
                <div key={field.id} className="space-y-1.5">
                    <Label htmlFor={field.id}>{field.label}</Label>
                    <Input
                        id={field.id}
                        type="date"
                        className="w-44"
                        value={field.value}
                        onChange={(event) => field.onChange(event.target.value)}
                    />
                </div>
            ))}
            <Button type="button" onClick={onRun} disabled={running}>
                {running ? (
                    <LoaderCircle
                        aria-hidden="true"
                        className="size-4 animate-spin"
                    />
                ) : null}
                Run
            </Button>
        </div>
    );
}

type StatementRow =
    | { kind: "section"; label: string }
    | { kind: "line"; label: string; amount: number | string }
    | { kind: "total"; label: string; amount: number | string }
    | {
          kind: "net";
          label: string;
          amount: number | string;
          negative?: boolean;
      };

function StatementTable({
    rows,
    emptyLabel = "No data in this period.",
    generatedAt,
}: {
    rows: StatementRow[];
    emptyLabel?: string;
    generatedAt?: string;
}) {
    const hasLines = rows.some((row) => row.kind === "line");
    return (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
            <table className="w-full text-sm">
                <tbody>
                    {!hasLines ? (
                        <tr>
                            <td className="px-4 py-8 text-center text-sm text-muted-foreground">
                                {emptyLabel}
                            </td>
                        </tr>
                    ) : (
                        rows.map((row, index) => {
                            if (row.kind === "section") {
                                return (
                                    <tr
                                        key={index}
                                        className="border-b border-border/60 bg-muted/40"
                                    >
                                        <td className="px-4 py-2 font-display text-sm font-semibold text-foreground">
                                            {row.label}
                                        </td>
                                        <td className="px-4 py-2 text-right font-display text-sm font-semibold text-foreground">
                                            Amount
                                        </td>
                                    </tr>
                                );
                            }
                            const amountClass =
                                row.kind === "net"
                                    ? cn(
                                          "font-display text-base font-semibold",
                                          row.negative
                                              ? "text-destructive"
                                              : "text-primary",
                                      )
                                    : row.kind === "total"
                                      ? "border-t border-border/70 font-semibold text-foreground"
                                      : "tabular-nums text-muted-foreground";
                            const labelClass =
                                row.kind === "total"
                                    ? "border-t border-border/70 font-medium text-foreground"
                                    : row.kind === "net"
                                      ? "border-t-2 border-double border-border font-display font-semibold text-foreground"
                                      : "text-muted-foreground";
                            return (
                                <tr
                                    key={index}
                                    className="border-b border-border/40 last:border-b-0"
                                >
                                    <td className={cn("px-4 py-2", labelClass)}>
                                        {row.label}
                                    </td>
                                    <td
                                        className={cn(
                                            "px-4 py-2 text-right",
                                            amountClass,
                                        )}
                                    >
                                        {formatMoney(row.amount)}
                                    </td>
                                </tr>
                            );
                        })
                    )}
                </tbody>
            </table>
            {generatedAt ? (
                <p className="border-t border-border/40 px-4 py-2 text-xs text-muted-foreground">
                    Generated {generatedAt}
                </p>
            ) : null}
        </div>
    );
}

const tbColumns: FinanceColumn<TrialBalance["rows"][number]>[] = [
    {
        label: "Code",
        render: (row) => <code className="font-mono text-xs">{row.code}</code>,
    },
    { label: "Account", render: (row) => row.name },
    { label: "Type", render: (row) => ACCOUNT_TYPE_LABELS[row.account_type] },
    { label: "Debit", align: "right", render: (row) => formatMoney(row.debit) },
    {
        label: "Credit",
        align: "right",
        render: (row) => formatMoney(row.credit),
    },
    {
        label: "Balance",
        align: "right",
        render: (row) => (
            <span className="tabular-nums">
                {formatMoney(toMoney(row.debit) - toMoney(row.credit))}
            </span>
        ),
    },
];

function TrialBalanceView({ periods }: { periods: FiscalPeriod[] }) {
    const [asOf, setAsOf] = useState(today());
    const [periodValue, setPeriodValue] =
        useState<PeriodValue>(defaultPeriodValue());
    const [data, setData] = useState<TrialBalance | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const run = useCallback(async (date: string) => {
        setLoading(true);
        setError(null);
        try {
            setData(await getTrialBalance(date));
        } catch (err) {
            setError(errorMessage(err, "Could not load the trial balance."));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void run(asOf);
    }, [asOf, run]);

    return (
        <div className="space-y-4">
            <PeriodSelector
                value={periodValue}
                onChange={(value) => {
                    setPeriodValue(value);
                    setAsOf(resolvePeriodRange(value).asOf);
                }}
                periods={periods}
                label="Report period"
            />
            <ReportToolbar
                fields={[
                    {
                        id: "tb-asof",
                        label: "As of",
                        value: asOf,
                        onChange: setAsOf,
                    },
                ]}
                onRun={() => void run(asOf)}
                running={loading}
            />
            {loading ? <TableSkeleton rows={6} /> : null}
            {error ? (
                <FinanceErrorState
                    message={error}
                    onRetry={() => void run(asOf)}
                />
            ) : null}
            {data && !loading ? (
                <FinanceTable
                    columns={tbColumns}
                    rows={data.rows}
                    getKey={(row) => row.account_id}
                    emptyMessage="No posted entries in this period."
                    footer={
                        <span className="flex justify-between gap-4">
                            <span>Totals</span>
                            <span className="tabular-nums">
                                {formatMoney(data.total_debit)} /{" "}
                                {formatMoney(data.total_credit)}
                            </span>
                        </span>
                    }
                />
            ) : null}
            {data && !loading ? (
                <p className="text-xs text-muted-foreground">
                    Generated {new Date().toLocaleString()}
                </p>
            ) : null}
        </div>
    );
}

function ProfitAndLossView({ periods }: { periods: FiscalPeriod[] }) {
    const [fromDate, setFromDate] = useState(firstOfMonth());
    const [toDate, setToDate] = useState(today());
    const [periodValue, setPeriodValue] =
        useState<PeriodValue>(defaultPeriodValue());
    const [data, setData] = useState<ProfitAndLoss | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const run = useCallback(async (from: string, to: string) => {
        setLoading(true);
        setError(null);
        try {
            setData(await getProfitAndLoss(from, to));
        } catch (err) {
            setError(
                errorMessage(
                    err,
                    "Could not load the profit and loss statement.",
                ),
            );
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void run(fromDate, toDate);
    }, [fromDate, toDate, run]);

    if (loading) return <TableSkeleton rows={6} />;
    if (error)
        return (
            <FinanceErrorState
                message={error}
                onRetry={() => void run(fromDate, toDate)}
            />
        );
    if (!data) return null;

    return (
        <div className="space-y-5">
            <PeriodSelector
                value={periodValue}
                onChange={(value) => {
                    setPeriodValue(value);
                    const range = resolvePeriodRange(value);
                    if (value.granularity === "all") {
                        setFromDate(firstOfMonth());
                        setToDate(today());
                    } else {
                        setFromDate(range.from ?? firstOfMonth());
                        setToDate(range.to ?? today());
                    }
                }}
                periods={periods}
                label="Report period"
            />
            <ReportToolbar
                fields={[
                    {
                        id: "pnl-from",
                        label: "From",
                        value: fromDate,
                        onChange: setFromDate,
                    },
                    {
                        id: "pnl-to",
                        label: "To",
                        value: toDate,
                        onChange: setToDate,
                    },
                ]}
                onRun={() => void run(fromDate, toDate)}
                running={loading}
            />
            <StatementTable
                rows={[
                    { kind: "section", label: "Revenue" },
                    ...data.revenue.map((line) => ({
                        kind: "line" as const,
                        label: `${line.code} · ${line.name}`,
                        amount: line.amount,
                    })),
                    {
                        kind: "total",
                        label: "Total revenue",
                        amount: data.total_revenue,
                    },
                    { kind: "section", label: "Expenses" },
                    ...data.expenses.map((line) => ({
                        kind: "line" as const,
                        label: `${line.code} · ${line.name}`,
                        amount: line.amount,
                    })),
                    {
                        kind: "total",
                        label: "Total expenses",
                        amount: data.total_expenses,
                    },
                    {
                        kind: "net",
                        label: "Net income",
                        amount: data.net_income,
                        negative: toMoney(data.net_income) < 0,
                    },
                ]}
                emptyLabel="No revenue or expenses posted in this period."
                generatedAt={new Date().toLocaleString()}
            />
        </div>
    );
}

function BalanceSheetView({ periods }: { periods: FiscalPeriod[] }) {
    const [asOf, setAsOf] = useState(today());
    const [periodValue, setPeriodValue] =
        useState<PeriodValue>(defaultPeriodValue());
    const [data, setData] = useState<BalanceSheet | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const run = useCallback(async (date: string) => {
        setLoading(true);
        setError(null);
        try {
            setData(await getBalanceSheet(date));
        } catch (err) {
            setError(errorMessage(err, "Could not load the balance sheet."));
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        void run(asOf);
    }, [asOf, run]);

    if (loading) return <TableSkeleton rows={6} />;
    if (error)
        return (
            <FinanceErrorState message={error} onRetry={() => void run(asOf)} />
        );
    if (!data) return null;

    return (
        <div className="space-y-5">
            <PeriodSelector
                value={periodValue}
                onChange={(value) => {
                    setPeriodValue(value);
                    setAsOf(resolvePeriodRange(value).asOf);
                }}
                periods={periods}
                label="Report period"
            />
            <ReportToolbar
                fields={[
                    {
                        id: "bs-asof",
                        label: "As of",
                        value: asOf,
                        onChange: setAsOf,
                    },
                ]}
                onRun={() => void run(asOf)}
                running={loading}
            />
            <StatementTable
                rows={[
                    { kind: "section", label: "Assets" },
                    ...data.assets.map((line) => ({
                        kind: "line" as const,
                        label: `${line.code} · ${line.name}`,
                        amount: line.balance,
                    })),
                    {
                        kind: "total",
                        label: "Total assets",
                        amount: data.total_assets,
                    },
                    { kind: "section", label: "Liabilities" },
                    ...data.liabilities.map((line) => ({
                        kind: "line" as const,
                        label: `${line.code} · ${line.name}`,
                        amount: line.balance,
                    })),
                    {
                        kind: "total",
                        label: "Total liabilities",
                        amount: data.total_liabilities,
                    },
                    { kind: "section", label: "Equity" },
                    ...data.equity.map((line) => ({
                        kind: "line" as const,
                        label: `${line.code} · ${line.name}`,
                        amount: line.balance,
                    })),
                    {
                        kind: "total",
                        label: "Total equity",
                        amount: data.total_equity,
                    },
                    {
                        kind: "net",
                        label: "Balance check (assets − liabilities − equity)",
                        amount:
                            toMoney(data.total_assets) -
                            toMoney(data.total_liabilities) -
                            toMoney(data.total_equity),
                    },
                ]}
                emptyLabel="No balances in this period."
                generatedAt={new Date().toLocaleString()}
            />
        </div>
    );
}

export function FinanceReports() {
    const [report, setReport] = useState<ReportKey>("trial-balance");
    const [periods, setPeriods] = useState<FiscalPeriod[]>([]);

    useEffect(() => {
        void listFiscalPeriods()
            .then(setPeriods)
            .catch(() => undefined);
    }, []);

    return (
        <div className="space-y-6">
            <PageHeader
                title="Statements"
                description="Financial statements derived from posted journal entries."
                icon={BarChart3}
            />

            <div
                role="tablist"
                aria-label="Financial reports"
                className="inline-flex rounded-lg border border-border bg-card p-0.5"
            >
                {REPORT_TABS.map((tab) => (
                    <button
                        key={tab.key}
                        type="button"
                        role="tab"
                        aria-selected={report === tab.key}
                        onClick={() => setReport(tab.key)}
                        className={cn(
                            "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                            report === tab.key
                                ? "bg-primary text-primary-foreground"
                                : "text-muted-foreground hover:text-foreground",
                        )}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {report === "trial-balance" ? (
                <TrialBalanceView periods={periods} />
            ) : null}
            {report === "profit-and-loss" ? (
                <ProfitAndLossView periods={periods} />
            ) : null}
            {report === "balance-sheet" ? (
                <BalanceSheetView periods={periods} />
            ) : null}
        </div>
    );
}
