"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
    getCashflowProjection,
    getComparativePnl,
    getAging,
    type ArAging,
    type BalanceSheet,
    type CashflowProjection,
    type ComparativePnl,
    type FiscalPeriod,
    type ProfitAndLoss,
    type TrialBalance,
    type TrialBalanceRow,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import {
    ACCOUNT_TYPE_LABELS,
    type AccountType,
    formatMoney,
    toMoney,
} from "@/lib/finance/format";
import {
    classifyAccount,
    BS_SECTION_ORDER,
    SECTION_LABELS,
    TB_TYPE_ORDER,
    type StatementSection,
} from "@/lib/finance/account-classification";
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
import {
    ComparativePnlWidget,
    CashflowWidget,
    ArAgingWidget,
} from "@/features/finance/components/automation-widgets";
import { cn } from "@/lib/utils";

type ReportKey = "trial-balance" | "profit-and-loss" | "balance-sheet" | "automation";

const REPORT_TABS: { key: ReportKey; label: string }[] = [
    { key: "trial-balance", label: "Trial Balance" },
    { key: "profit-and-loss", label: "Profit & Loss" },
    { key: "balance-sheet", label: "Balance Sheet" },
    { key: "automation", label: "Automation" },
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

// ---------------------------------------------------------------------------
// StatementTable (enhanced with indent + subtotal)
// ---------------------------------------------------------------------------

type StatementRow =
    | { kind: "section"; label: string }
    | {
          kind: "line";
          label: string;
          amount: number | string;
          indent?: boolean;
      }
    | { kind: "total"; label: string; amount: number | string }
    | { kind: "subtotal"; label: string; amount: number | string }
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
    reportHeader,
}: {
    rows: StatementRow[];
    emptyLabel?: string;
    generatedAt?: string;
    reportHeader?: { title: string; subtitle: string };
}) {
    const hasLines = rows.some((row) => row.kind === "line");
    return (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
            {reportHeader ? (
                <div className="border-b border-border/60 px-4 py-3">
                    <h3 className="text-sm font-display font-semibold text-foreground">
                        {reportHeader.title}
                    </h3>
                    <p className="text-xs text-muted-foreground">
                        {reportHeader.subtitle}
                    </p>
                </div>
            ) : null}
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
                            const isSubtotal = row.kind === "subtotal";
                            const amountClass =
                                row.kind === "net"
                                    ? cn(
                                          "font-display text-base font-semibold",
                                          row.negative
                                              ? "text-destructive"
                                              : "text-primary",
                                      )
                                    : isSubtotal
                                      ? "border-t border-border/70 font-semibold text-foreground"
                                      : row.kind === "total"
                                        ? "border-t border-border/70 font-bold text-foreground"
                                        : "tabular-nums text-muted-foreground";
                            const labelClass =
                                row.kind === "total"
                                    ? "border-t border-border/70 font-bold text-foreground"
                                    : isSubtotal
                                      ? "border-t border-border/70 font-medium text-foreground"
                                      : row.kind === "net"
                                        ? "border-t-2 border-double border-border font-display font-semibold text-foreground"
                                        : "text-muted-foreground";
                            return (
                                <tr
                                    key={index}
                                    className="border-b border-border/40 last:border-b-0"
                                >
                                    <td
                                        className={cn(
                                            "px-4 py-2",
                                            labelClass,
                                            row.kind === "line" && row.indent && "pl-8",
                                        )}
                                    >
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

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type LineItem = { account_id: string; code: string; name: string };

function groupBySection<T extends LineItem>(
    items: T[],
    accountType: AccountType,
    sortOrder: Record<StatementSection, number>,
): { section: StatementSection; lines: T[] }[] {
    const map = new Map<StatementSection, T[]>();
    for (const item of items) {
        const section = classifyAccount(item.code, accountType);
        const existing = map.get(section);
        if (existing) {
            existing.push(item);
        } else {
            map.set(section, [item]);
        }
    }
    return [...map.entries()]
        .sort(([a], [b]) => sortOrder[a] - sortOrder[b])
        .map(([section, lines]) => ({
            section,
            lines: lines.sort((x, y) => x.code.localeCompare(y.code, undefined, { numeric: true })),
        }));
}

function sumAmounts<T extends { amount?: number | string; balance?: number | string }>(
    items: T[],
    field: "amount" | "balance",
): number {
    return items.reduce<number>((sum, item) => {
        const raw = item[field];
        return sum + (raw === undefined ? 0 : toMoney(raw));
    }, 0);
}

function fmtDateLong(dateStr: string): string {
    const d = new Date(dateStr + "T00:00:00");
    return d.toLocaleDateString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
    });
}

// ---------------------------------------------------------------------------
// Trial Balance
// ---------------------------------------------------------------------------

const tbColumns: FinanceColumn<TrialBalanceRow & { _sorted: number }>[] = [
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

    const sortedRows = useMemo(() => {
        if (!data) return [];
        return [...data.rows].sort((a, b) => {
            const typeDiff =
                TB_TYPE_ORDER[a.account_type] - TB_TYPE_ORDER[b.account_type];
            if (typeDiff !== 0) return typeDiff;
            return a.code.localeCompare(b.code, undefined, { numeric: true });
        });
    }, [data]);

    const isBalanced = data
        ? Math.abs(toMoney(data.total_debit) - toMoney(data.total_credit)) < 0.01
        : false;

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
                    rows={sortedRows.map((row) => ({
                        ...row,
                        _sorted: 0,
                    }))}
                    getKey={(row) => row.account_id}
                    emptyMessage="No posted entries in this period."
                    footer={
                        <div className="space-y-2">
                            <span className="flex justify-between gap-4">
                                <span className="font-semibold">Totals</span>
                                <span className="tabular-nums">
                                    {formatMoney(data.total_debit)} /{" "}
                                    {formatMoney(data.total_credit)}
                                </span>
                            </span>
                            <div className="flex items-center justify-end gap-2">
                                <span
                                    className={cn(
                                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                                        isBalanced
                                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
                                            : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
                                    )}
                                >
                                    {isBalanced
                                        ? "\u2713 Balanced"
                                        : `\u2717 Imbalance of ${formatMoney(Math.abs(toMoney(data.total_debit) - toMoney(data.total_credit)))}`}
                                </span>
                            </div>
                        </div>
                    }
                />
            ) : null}
        </div>
    );
}

// ---------------------------------------------------------------------------
// Profit & Loss
// ---------------------------------------------------------------------------

function buildPnlRows(data: ProfitAndLoss): StatementRow[] {
    const rows: StatementRow[] = [];

    // Revenue section
    rows.push({ kind: "section", label: "Revenue" });
    const sortedRevenue = [...data.revenue].sort((a, b) =>
        a.code.localeCompare(b.code, undefined, { numeric: true }),
    );
    for (const line of sortedRevenue) {
        rows.push({
            kind: "line",
            label: `${line.code} \u00b7 ${line.name}`,
            amount: line.amount,
        });
    }
    rows.push({ kind: "total", label: "Total Revenue", amount: data.total_revenue });

    // Split expenses by code range
    const cogs: typeof data.expenses = [];
    const operating: typeof data.expenses = [];
    const otherIncome: typeof data.expenses = [];
    const otherExpense: typeof data.expenses = [];

    for (const line of data.expenses) {
        const section = classifyAccount(line.code, "expense");
        if (section === "cogs") cogs.push(line);
        else if (section === "other_expense") otherExpense.push(line);
        else operating.push(line); // operating_expense or fallback
    }

    // Cost of Goods Sold (only show if non-empty)
    if (cogs.length > 0) {
        cogs.sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));
        const totalCogs = sumAmounts(cogs, "amount");
        rows.push({ kind: "section", label: "Cost of Goods Sold" });
        for (const line of cogs) {
            rows.push({
                kind: "line",
                label: `${line.code} \u00b7 ${line.name}`,
                amount: line.amount,
            });
        }
        rows.push({ kind: "total", label: "Total Cost of Goods Sold", amount: totalCogs });

        const grossProfit = toMoney(data.total_revenue) - totalCogs;
        rows.push({ kind: "subtotal", label: "Gross Profit", amount: grossProfit });
    }

    // Operating Expenses
    if (operating.length > 0) {
        operating.sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));
        const totalOperating = sumAmounts(operating, "amount");
        rows.push({ kind: "section", label: "Operating Expenses" });
        for (const line of operating) {
            rows.push({
                kind: "line",
                label: `${line.code} \u00b7 ${line.name}`,
                amount: line.amount,
            });
        }
        rows.push({ kind: "total", label: "Total Operating Expenses", amount: totalOperating });
    }

    // Other Income / Expenses (only show if non-empty)
    const hasOther = otherIncome.length > 0 || otherExpense.length > 0;
    if (hasOther) {
        rows.push({ kind: "section", label: "Other Income / Expenses" });
        otherIncome.sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));
        for (const line of otherIncome) {
            rows.push({
                kind: "line",
                label: `${line.code} \u00b7 ${line.name}`,
                amount: line.amount,
            });
        }
        otherExpense.sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));
        for (const line of otherExpense) {
            rows.push({
                kind: "line",
                label: `${line.code} \u00b7 ${line.name}`,
                amount: line.amount,
            });
        }
        const totalOther =
            sumAmounts(otherIncome, "amount") - sumAmounts(otherExpense, "amount");
        rows.push({ kind: "total", label: "Total Other", amount: totalOther });
    }

    // Net Income
    rows.push({
        kind: "net",
        label: "Net Income",
        amount: data.net_income,
        negative: toMoney(data.net_income) < 0,
    });

    return rows;
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

    const rows = useMemo(
        () => (data ? buildPnlRows(data) : []),
        [data],
    );

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
                rows={rows}
                emptyLabel="No revenue or expenses posted in this period."
                generatedAt={new Date().toLocaleString()}
                reportHeader={{
                    title: "Profit & Loss Statement",
                    subtitle: `${fmtDateLong(fromDate)} \u2013 ${fmtDateLong(toDate)}`,
                }}
            />
        </div>
    );
}

// ---------------------------------------------------------------------------
// Balance Sheet
// ---------------------------------------------------------------------------

function buildBalanceSheetRows(data: BalanceSheet): StatementRow[] {
    const rows: StatementRow[] = [];

    // ---- Assets ----
    rows.push({ kind: "section", label: "Assets" });

    const assetGroups = groupBySection(data.assets, "asset", BS_SECTION_ORDER);
    let totalAssets = 0;

    for (const { section, lines } of assetGroups) {
        const sectionTotal = sumAmounts(lines, "balance");
        totalAssets += sectionTotal;
        rows.push({
            kind: "section",
            label: SECTION_LABELS[section],
        });
        for (const line of lines) {
            rows.push({
                kind: "line",
                label: `${line.code} \u00b7 ${line.name}`,
                amount: line.balance,
                indent: true,
            });
        }
        rows.push({
            kind: "subtotal",
            label: `Total ${SECTION_LABELS[section]}`,
            amount: sectionTotal,
        });
    }
    rows.push({ kind: "total", label: "Total Assets", amount: totalAssets });

    // ---- Liabilities ----
    rows.push({ kind: "section", label: "Liabilities" });

    const liabGroups = groupBySection(
        data.liabilities,
        "liability",
        BS_SECTION_ORDER,
    );
    let totalLiabilities = 0;

    for (const { section, lines } of liabGroups) {
        const sectionTotal = sumAmounts(lines, "balance");
        totalLiabilities += sectionTotal;
        rows.push({
            kind: "section",
            label: SECTION_LABELS[section],
        });
        for (const line of lines) {
            rows.push({
                kind: "line",
                label: `${line.code} \u00b7 ${line.name}`,
                amount: line.balance,
                indent: true,
            });
        }
        rows.push({
            kind: "subtotal",
            label: `Total ${SECTION_LABELS[section]}`,
            amount: sectionTotal,
        });
    }
    rows.push({
        kind: "total",
        label: "Total Liabilities",
        amount: totalLiabilities,
    });

    // ---- Equity ----
    rows.push({ kind: "section", label: "Equity" });

    const sortedEquity = [...data.equity].sort((a, b) =>
        a.code.localeCompare(b.code, undefined, { numeric: true }),
    );
    for (const line of sortedEquity) {
        rows.push({
            kind: "line",
            label: `${line.code} \u00b7 ${line.name}`,
            amount: line.balance,
        });
    }
    rows.push({
        kind: "total",
        label: "Total Equity",
        amount: data.total_equity,
    });

    // Total Liabilities & Equity
    const totalLiabEq = totalLiabilities + toMoney(data.total_equity);
    rows.push({
        kind: "net",
        label: "Total Liabilities & Equity",
        amount: totalLiabEq,
        negative: toMoney(totalAssets) - totalLiabEq !== 0,
    });

    return rows;
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

    const rows = useMemo(
        () => (data ? buildBalanceSheetRows(data) : []),
        [data],
    );

    if (loading) return <TableSkeleton rows={6} />;
    if (error)
        return (
            <FinanceErrorState message={error} onRetry={() => void run(asOf)} />
        );
    if (!data) return null;

    const diff =
        toMoney(data.total_assets) -
        toMoney(data.total_liabilities) -
        toMoney(data.total_equity);
    const isBalanced = Math.abs(diff) < 0.01;

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
                rows={rows}
                emptyLabel="No balances in this period."
                generatedAt={new Date().toLocaleString()}
                reportHeader={{
                    title: "Balance Sheet",
                    subtitle: `As of ${fmtDateLong(asOf)}`,
                }}
            />
            <div className="flex items-center justify-end">
                <span
                    className={cn(
                        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
                        isBalanced
                            ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400"
                            : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400",
                    )}
                >
                    {isBalanced
                        ? "\u2713 Balanced"
                        : `\u2717 Difference of ${formatMoney(Math.abs(diff))}`}
                </span>
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Automation reports
// ---------------------------------------------------------------------------

function dateYearsAgo(years: number): string {
    const d = new Date();
    d.setFullYear(d.getFullYear() - years);
    return d.toISOString().slice(0, 10);
}

function AutomationView() {
    const todayStr = today();
    const [aging, setAging] = useState<ArAging | null>(null);
    const [agingLoading, setAgingLoading] = useState(true);
    const [projection, setProjection] = useState<CashflowProjection | null>(null);
    const [comparative, setComparative] = useState<ComparativePnl | null>(null);
    const [compLoading, setCompLoading] = useState(true);
    const [compError, setCompError] = useState<string | null>(null);
    const [agingError, setAgingError] = useState<string | null>(null);
    const [projError, setProjError] = useState<string | null>(null);

    // Backdate one full year for the prior period.
    const priorFrom = dateYearsAgo(1);
    const currentFrom = dateYearsAgo(0).slice(0, 4) + "-01-01";

    const loadAging = useCallback(async () => {
        setAgingLoading(true);
        setAgingError(null);
        try {
            setAging(await getAging(todayStr));
        } catch (err) {
            setAgingError(errorMessage(err, "Could not load AR aging."));
        } finally {
            setAgingLoading(false);
        }
    }, [todayStr]);

    const loadProjection = useCallback(async () => {
        setProjError(null);
        try {
            setProjection(await getCashflowProjection(todayStr));
        } catch (err) {
            setProjError(errorMessage(err, "Could not load the cash-flow projection."));
        }
    }, [todayStr]);

    const loadComparative = useCallback(async () => {
        setCompLoading(true);
        setCompError(null);
        try {
            setComparative(
                await getComparativePnl(currentFrom, todayStr, priorFrom, todayStr),
            );
        } catch (err) {
            setCompError(errorMessage(err, "Could not load the comparative P&L."));
        } finally {
            setCompLoading(false);
        }
    }, [currentFrom, priorFrom, todayStr]);

    useEffect(() => {
        void loadAging();
    }, [loadAging]);
    useEffect(() => {
        void loadProjection();
    }, [loadProjection]);
    useEffect(() => {
        void loadComparative();
    }, [loadComparative]);

    const caption = comparative
        ? `${fmtDateLong(comparative.current_from)} \u2013 ${fmtDateLong(comparative.current_to)} vs ${fmtDateLong(comparative.prior_from)} \u2013 ${fmtDateLong(comparative.prior_to)}`
        : "Current vs prior period";

    return (
        <div className="space-y-6">
            <section className="space-y-4">
                <ArAgingWidget aging={aging} loading={agingLoading} />
                {agingError ? (
                    <FinanceErrorState message={agingError} onRetry={() => void loadAging()} />
                ) : null}
            </section>
            <section className="space-y-4">
                <CashflowWidget projection={projection ?? { positions: [] }} />
                {projError ? (
                    <FinanceErrorState
                        message={projError}
                        onRetry={() => void loadProjection()}
                    />
                ) : null}
            </section>
            <section className="space-y-4">
                <ComparativePnlWidget
                    rows={comparative?.rows ?? []}
                    caption={caption}
                    loading={compLoading}
                    error={compError}
                    onRetry={() => void loadComparative()}
                />
            </section>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

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
            {report === "automation" ? <AutomationView /> : null}
        </div>
    );
}
