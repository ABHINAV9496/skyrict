"use client";

import { useCallback, useEffect, useState } from "react";
import {
    CircleCheck,
    LoaderCircle,
    Lock,
    NotebookPen,
    Play,
    Plus,
    Trash2,
} from "lucide-react";

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
    activateBudget,
    addBudgetLines,
    closeBudget,
    createBudget,
    getBudgetVariance,
    listBudgets,
    type Budget,
    type BudgetStatus,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatMoney } from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import { StatusBadge } from "@/features/finance/components/status-badge";
import {
    FinanceEmptyState,
    FinanceErrorState,
} from "@/features/finance/components/state-cards";
import { TableToolbar } from "@/features/finance/components/table-toolbar";

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; budgets: Budget[] };

const budgetTone = (status: BudgetStatus) =>
    status === "draft"
        ? "muted"
        : status === "active"
          ? "success"
          : "warning";

const budgetLabel = (status: BudgetStatus) =>
    status.charAt(0).toUpperCase() + status.slice(1);

function CreateBudgetDialog({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onCreated: () => void;
}) {
    const setOpen = onOpenChange;
    const [name, setName] = useState("");
    const [fiscalYear, setFiscalYear] = useState(
        String(new Date().getFullYear()),
    );
    const [description, setDescription] = useState("");
    const [lines, setLines] = useState<{ account_code: string; amount: string }[]>(
        [{ account_code: "", amount: "" }],
    );
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    async function submit() {
        const year = Number(fiscalYear);
        if (!name.trim() || !Number.isInteger(year) || year < 2000 || year > 2200) {
            setSubmitError("Enter a name and a valid fiscal year.");
            return;
        }
        const payload = lines
            .filter((line) => line.account_code.trim() && Number(line.amount) > 0)
            .map((line) => ({
                account_code: line.account_code.trim(),
                amount: Number(line.amount),
            }));
        setSubmitError(null);
        setSubmitting(true);
        try {
            await createBudget({
                name: name.trim(),
                fiscal_year: year,
                description: description.trim() || null,
                lines: payload,
            });
            setOpen(false);
            onCreated();
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The budget could not be created.",
            );
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogTrigger asChild>
                <Button>
                    <Plus aria-hidden="true" className="size-4" />
                    New budget
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-xl">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <NotebookPen aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>New budget</DialogTitle>
                        <DialogDescription>
                            An annual spending plan for a fiscal year, broken
                            down by chart of accounts codes.
                        </DialogDescription>
                    </DialogHeader>
                </div>
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                    className="max-h-[min(85vh,40rem)] space-y-4 overflow-y-auto pr-1"
                >
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="budget-name">Name</Label>
                            <Input
                                id="budget-name"
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                placeholder="e.g. FY 2026 Operating Budget"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="budget-year">Fiscal year</Label>
                            <Input
                                id="budget-year"
                                type="number"
                                inputMode="numeric"
                                value={fiscalYear}
                                onChange={(event) =>
                                    setFiscalYear(event.target.value)
                                }
                            />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="budget-description">Description</Label>
                        <Input
                            id="budget-description"
                            value={description}
                            onChange={(event) => setDescription(event.target.value)}
                            placeholder="Optional"
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>Budget lines</Label>
                        {lines.map((line, index) => (
                            <div
                                key={index}
                                className="flex items-center gap-2"
                            >
                                <Input
                                    aria-label={`Account code ${index + 1}`}
                                    placeholder="e.g. 5100"
                                    className="flex-1 font-mono"
                                    value={line.account_code}
                                    onChange={(event) =>
                                        setLines((prev) =>
                                            prev.map((l, i) =>
                                                i === index
                                                    ? {
                                                          ...l,
                                                          account_code:
                                                              event.target
                                                                  .value,
                                                      }
                                                    : l,
                                            ),
                                        )
                                    }
                                />
                                <Input
                                    aria-label={`Amount ${index + 1}`}
                                    type="number"
                                    inputMode="decimal"
                                    min="0"
                                    step="0.01"
                                    placeholder="0.00"
                                    className="w-32"
                                    value={line.amount}
                                    onChange={(event) =>
                                        setLines((prev) =>
                                            prev.map((l, i) =>
                                                i === index
                                                    ? {
                                                          ...l,
                                                          amount:
                                                              event.target
                                                                  .value,
                                                      }
                                                    : l,
                                            ),
                                        )
                                    }
                                />
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    aria-label="Remove line"
                                    disabled={lines.length === 1}
                                    onClick={() =>
                                        setLines((prev) =>
                                            prev.filter((_, i) => i !== index),
                                        )
                                    }
                                >
                                    <Trash2
                                        aria-hidden="true"
                                        className="size-3.5"
                                    />
                                </Button>
                            </div>
                        ))}
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                                setLines((prev) => [
                                    ...prev,
                                    { account_code: "", amount: "" },
                                ])
                            }
                        >
                            <Plus aria-hidden="true" className="size-3.5" />
                            Add line
                        </Button>
                    </div>
                    {submitError ? (
                        <p
                            role="alert"
                            className="text-sm font-medium text-destructive"
                        >
                            {submitError}
                        </p>
                    ) : null}
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => setOpen(false)}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting}>
                            {submitting ? (
                                <LoaderCircle
                                    aria-hidden="true"
                                    className="size-4 animate-spin"
                                />
                            ) : (
                                <Plus aria-hidden="true" className="size-4" />
                            )}
                            Save budget
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function BudgetRowActions({ budget }: { budget: Budget }) {
    const [varianceOpen, setVarianceOpen] = useState(false);
    const [linesOpen, setLinesOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function run(action: () => Promise<unknown>) {
        setBusy(true);
        setError(null);
        try {
            await action();
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "The action failed. Try again.",
            );
        } finally {
            setBusy(false);
        }
    }

    return (
        <span className="inline-flex items-center gap-1">
            {budget.status === "draft" ? (
                <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => void run(() => activateBudget(budget.id))}
                >
                    <Play aria-hidden="true" className="size-3.5" />
                    Activate
                </Button>
            ) : null}
            {budget.status === "active" ? (
                <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => void run(() => closeBudget(budget.id))}
                >
                    <Lock aria-hidden="true" className="size-3.5" />
                    Close
                </Button>
            ) : null}
            <Button
                variant="outline"
                size="sm"
                onClick={() => setLinesOpen(true)}
            >
                <Plus aria-hidden="true" className="size-3.5" />
                Add lines
            </Button>
            <Button variant="outline" size="sm" onClick={() => setVarianceOpen(true)}>
                Variance
            </Button>
            {error ? (
                <span
                    role="alert"
                    className="text-xs font-medium text-destructive"
                >
                    {error}
                </span>
            ) : null}
            <BudgetVarianceDialog
                budget={budget}
                open={varianceOpen}
                onOpenChange={setVarianceOpen}
            />
            <BudgetLinesDialog
                budget={budget}
                open={linesOpen}
                onOpenChange={setLinesOpen}
            />
        </span>
    );
}

function BudgetVarianceDialog({
    budget,
    open,
    onOpenChange,
}: {
    budget: Budget;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}) {
    const [state, setState] = useState<
        | { state: "loading" }
        | { state: "error"; message: string }
        | { state: "ready"; variance: Awaited<ReturnType<typeof getBudgetVariance>> }
    >({ state: "loading" });

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        setState({ state: "loading" });
        void getBudgetVariance(budget.id)
            .then((variance) => {
                if (!cancelled) setState({ state: "ready", variance });
            })
            .catch((error) => {
                if (!cancelled)
                    setState({
                        state: "error",
                        message:
                            error instanceof ApiError
                                ? error.message
                                : "Could not load budget variance.",
                    });
            });
        return () => {
            cancelled = true;
        };
    }, [open, budget.id]);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-2xl">
                <DialogHeader>
                    <DialogTitle>Variance — {budget.name}</DialogTitle>
                    <DialogDescription>
                        Planned vs actual spending by account code.
                    </DialogDescription>
                </DialogHeader>
                {state.state === "loading" ? <TableSkeleton rows={4} /> : null}
                {state.state === "error" ? (
                    <p
                        role="alert"
                        className="text-sm font-medium text-destructive"
                    >
                        {state.message}
                    </p>
                ) : null}
                {state.state === "ready" ? (
                    <div className="space-y-4">
                        <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                            <div className="rounded-lg border border-border p-3">
                                <p className="text-xs text-muted-foreground">
                                    Planned
                                </p>
                                <p className="font-semibold tabular-nums">
                                    {formatMoney(state.variance.planned_total)}
                                </p>
                            </div>
                            <div className="rounded-lg border border-border p-3">
                                <p className="text-xs text-muted-foreground">
                                    Actual
                                </p>
                                <p className="font-semibold tabular-nums">
                                    {formatMoney(state.variance.actual_total)}
                                </p>
                            </div>
                            <div className="rounded-lg border border-border p-3">
                                <p className="text-xs text-muted-foreground">
                                    Variance
                                </p>
                                <p
                                    className={`font-semibold tabular-nums ${
                                        state.variance.variance_total < 0
                                            ? "text-destructive"
                                            : "text-emerald-600 dark:text-emerald-400"
                                    }`}
                                >
                                    {formatMoney(state.variance.variance_total)}
                                </p>
                            </div>
                            <div className="rounded-lg border border-border p-3">
                                <p className="text-xs text-muted-foreground">
                                    Flagged lines
                                </p>
                                <p className="font-semibold tabular-nums">
                                    {state.variance.flagged_count}
                                </p>
                            </div>
                        </div>
                        <FinanceTable
                            columns={[
                                {
                                    label: "Account",
                                    render: (line) => (
                                        <span className="font-mono">
                                            {line.account_code}
                                        </span>
                                    ),
                                },
                                {
                                    label: "Planned",
                                    align: "right",
                                    render: (line) => formatMoney(line.planned),
                                },
                                {
                                    label: "Actual",
                                    align: "right",
                                    render: (line) => formatMoney(line.actual),
                                },
                                {
                                    label: "Variance",
                                    align: "right",
                                    render: (line) => (
                                        <span
                                            className={
                                                line.variance < 0
                                                    ? "text-destructive"
                                                    : undefined
                                            }
                                        >
                                            {formatMoney(line.variance)}
                                        </span>
                                    ),
                                },
                                {
                                    label: "Flag",
                                    render: (line) =>
                                        line.flag === "ok" ? (
                                            <CircleCheck
                                                aria-label="On track"
                                                className="size-4 text-emerald-500"
                                            />
                                        ) : line.flag === "amber" ? (
                                            <StatusBadge tone="warning">
                                                Amber
                                            </StatusBadge>
                                        ) : (
                                            <StatusBadge tone="danger">
                                                Over
                                            </StatusBadge>
                                        ),
                                },
                            ]}
                            rows={state.variance.lines}
                            getKey={(line) => line.account_code}
                        />
                    </div>
                ) : null}
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        Close
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

function BudgetLinesDialog({
    budget,
    open,
    onOpenChange,
}: {
    budget: Budget;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}) {
    const [lines, setLines] = useState<{ account_code: string; amount: string }[]>(
        [{ account_code: "", amount: "" }],
    );
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open) {
            setLines([{ account_code: "", amount: "" }]);
            setSubmitError(null);
        }
    }, [open]);

    async function submit() {
        const payload = lines
            .filter((line) => line.account_code.trim() && Number(line.amount) > 0)
            .map((line) => ({
                account_code: line.account_code.trim(),
                amount: Number(line.amount),
            }));
        if (payload.length === 0) {
            setSubmitError("Add at least one account line.");
            return;
        }
        setSubmitError(null);
        setSubmitting(true);
        try {
            await addBudgetLines(budget.id, payload);
            onOpenChange(false);
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The lines could not be added.",
            );
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-xl">
                <DialogHeader>
                    <DialogTitle>Add lines — {budget.name}</DialogTitle>
                    <DialogDescription>
                        Extend the budget with more account codes.
                    </DialogDescription>
                </DialogHeader>
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                    className="space-y-4"
                >
                    <div className="space-y-2">
                        {lines.map((line, index) => (
                            <div key={index} className="flex items-center gap-2">
                                <Input
                                    aria-label={`Account code ${index + 1}`}
                                    placeholder="e.g. 5100"
                                    className="flex-1 font-mono"
                                    value={line.account_code}
                                    onChange={(event) =>
                                        setLines((prev) =>
                                            prev.map((l, i) =>
                                                i === index
                                                    ? {
                                                          ...l,
                                                          account_code:
                                                              event.target.value,
                                                      }
                                                    : l,
                                            ),
                                        )
                                    }
                                />
                                <Input
                                    aria-label={`Amount ${index + 1}`}
                                    type="number"
                                    inputMode="decimal"
                                    min="0"
                                    step="0.01"
                                    placeholder="0.00"
                                    className="w-32"
                                    value={line.amount}
                                    onChange={(event) =>
                                        setLines((prev) =>
                                            prev.map((l, i) =>
                                                i === index
                                                    ? {
                                                          ...l,
                                                          amount:
                                                              event.target.value,
                                                      }
                                                    : l,
                                            ),
                                        )
                                    }
                                />
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon-sm"
                                    aria-label="Remove line"
                                    disabled={lines.length === 1}
                                    onClick={() =>
                                        setLines((prev) =>
                                            prev.filter((_, i) => i !== index),
                                        )
                                    }
                                >
                                    <Trash2
                                        aria-hidden="true"
                                        className="size-3.5"
                                    />
                                </Button>
                            </div>
                        ))}
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() =>
                                setLines((prev) => [
                                    ...prev,
                                    { account_code: "", amount: "" },
                                ])
                            }
                        >
                            <Plus aria-hidden="true" className="size-3.5" />
                            Add line
                        </Button>
                    </div>
                    {submitError ? (
                        <p
                            role="alert"
                            className="text-sm font-medium text-destructive"
                        >
                            {submitError}
                        </p>
                    ) : null}
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={() => onOpenChange(false)}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" disabled={submitting}>
                            {submitting ? (
                                <LoaderCircle
                                    aria-hidden="true"
                                    className="size-4 animate-spin"
                                />
                            ) : null}
                            Save lines
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

const columns: FinanceColumn<Budget>[] = [
    { label: "Budget", render: (budget) => budget.name },
    {
        label: "Fiscal year",
        render: (budget) => (
            <span className="tabular-nums">{budget.fiscal_year}</span>
        ),
    },
    {
        label: "Status",
        render: (budget) => (
            <StatusBadge tone={budgetTone(budget.status)}>
                {budgetLabel(budget.status)}
            </StatusBadge>
        ),
    },
    {
        label: "Lines",
        align: "right",
        render: (budget) => (
            <span className="tabular-nums">{budget.lines.length}</span>
        ),
    },
    {
        label: "Planned",
        align: "right",
        render: (budget) => (
            <span className="tabular-nums">
                {formatMoney(
                    budget.lines.reduce((sum, line) => sum + line.amount, 0),
                )}
            </span>
        ),
    },
    {
        label: "",
        align: "right",
        render: (budget) => <BudgetRowActions budget={budget} />,
    },
];

export function FinanceBudgets() {
    const { permissions } = useModuleAccess();
    const canWrite = hasPermission(permissions, "erp.budget.write");
    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [query, setQuery] = useState("");
    const [statusTab, setStatusTab] = useState("all");
    const [createOpen, setCreateOpen] = useState(false);

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const budgets = await listBudgets();
            setStatus({ state: "ready", budgets });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load budgets.",
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
                    title="Budgets"
                    description="Annual spending plans tracked against actuals per account."
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
                    title="Budgets"
                    description="Annual spending plans tracked against actuals per account."
                    icon={NotebookPen}
                />
                <FinanceErrorState
                    message={status.message}
                    onRetry={() => void load()}
                />
            </div>
        );
    }

    const needle = query.trim().toLowerCase();
    const visibleBudgets = status.budgets.filter((budget) => {
        if (statusTab !== "all" && budget.status !== statusTab) return false;
        if (!needle) return true;
        return (
            budget.name.toLowerCase().includes(needle) ||
            String(budget.fiscal_year).includes(needle)
        );
    });

    const totalPlanned = status.budgets
        .filter((b) => b.status === "active")
        .reduce(
            (sum, budget) =>
                sum +
                budget.lines.reduce((lineSum, line) => lineSum + line.amount, 0),
            0,
        );

    return (
        <div className="space-y-6">
            <PageHeader
                title="Budgets"
                description="Annual spending plans tracked against actuals per account."
                icon={NotebookPen}
            />
            <TableToolbar
                searchPlaceholder="Search budgets…"
                searchValue={query}
                onSearchChange={setQuery}
                tabs={[
                    { key: "all", label: "All", count: status.budgets.length },
                    {
                        key: "draft",
                        label: "Draft",
                        count: status.budgets.filter((b) => b.status === "draft")
                            .length,
                    },
                    {
                        key: "active",
                        label: "Active",
                        count: status.budgets.filter((b) => b.status === "active")
                            .length,
                    },
                    {
                        key: "closed",
                        label: "Closed",
                        count: status.budgets.filter((b) => b.status === "closed")
                            .length,
                    },
                ]}
                activeTab={statusTab}
                onTabChange={setStatusTab}
                actions={
                    canWrite ? (
                        <CreateBudgetDialog
                            open={createOpen}
                            onOpenChange={setCreateOpen}
                            onCreated={() => void load()}
                        />
                    ) : null
                }
            />
            {visibleBudgets.length === 0 ? (
                <FinanceEmptyState
                    icon={NotebookPen}
                    title="No budgets yet"
                    description="Create a budget to plan spending and track variance by account."
                />
            ) : (
                <FinanceTable
                    columns={columns}
                    rows={visibleBudgets}
                    getKey={(budget) => budget.id}
                    footer={
                        <span className="flex justify-between gap-4">
                            <span>
                                {visibleBudgets.length} of{" "}
                                {status.budgets.length} budgets
                            </span>
                            <span className="tabular-nums">
                                Active planned total{" "}
                                {formatMoney(totalPlanned)}
                            </span>
                        </span>
                    }
                />
            )}
        </div>
    );
}