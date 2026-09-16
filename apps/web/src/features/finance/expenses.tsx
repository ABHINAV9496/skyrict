"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
    BadgeCheck,
    CircleX,
    LoaderCircle,
    Plus,
    ReceiptText,
    ShieldCheck,
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
    approveExpenseClaim,
    createExpensePolicy,
    listExpenseClaims,
    listExpensePolicies,
    listExpenseViolations,
    rejectExpenseClaim,
    submitExpenseClaim,
    type ExpenseClaim,
    type ExpenseClaimStatus,
    type ExpensePolicy,
    type ExpenseViolation,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/finance/format";
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

type PageTab = "policies" | "claims" | "violations";

type PoliciesStatus =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready" };

const claimTone: Record<ExpenseClaimStatus, "warning" | "success" | "danger"> =
    {
        submitted: "warning",
        approved: "success",
        rejected: "danger",
    };

const claimLabel: Record<ExpenseClaimStatus, string> = {
    submitted: "Submitted",
    approved: "Approved",
    rejected: "Rejected",
};

function PolicyDialog({
    open,
    onOpenChange,
    onSaved,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSaved: () => void;
}) {
    const setOpen = onOpenChange;
    const [category, setCategory] = useState("");
    const [name, setName] = useState("");
    const [capAmount, setCapAmount] = useState("");
    const [requiresReceipt, setRequiresReceipt] = useState(false);
    const [advanceLimit, setAdvanceLimit] = useState("");
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open) {
            setCategory("");
            setName("");
            setCapAmount("");
            setRequiresReceipt(false);
            setAdvanceLimit("");
            setSubmitError(null);
        }
    }, [open]);

    async function submit() {
        const cap = capAmount.trim() === "" ? null : Number(capAmount);
        const advance =
            advanceLimit.trim() === "" ? null : Number(advanceLimit);
        if (!category.trim()) {
            setSubmitError("A category is required.");
            return;
        }
        if (cap != null && (!Number.isFinite(cap) || cap < 0)) {
            setSubmitError("Cap amount must be zero or greater.");
            return;
        }
        if (advance != null && (!Number.isFinite(advance) || advance < 0)) {
            setSubmitError("Advance limit must be zero or greater.");
            return;
        }
        setSubmitError(null);
        setSubmitting(true);
        try {
            await createExpensePolicy({
                category: category.trim(),
                name: name.trim() || null,
                cap_amount: cap,
                requires_receipt: requiresReceipt,
                advance_limit: advance,
            });
            setOpen(false);
            onSaved();
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The policy could not be saved.",
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
                    New policy
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <ShieldCheck aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>
                            New expense policy
                        </DialogTitle>
                        <DialogDescription>
                            Rules that auto-approve or block claims per
                            category.
                        </DialogDescription>
                    </DialogHeader>
                </div>
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                    className="space-y-4"
                >
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="policy-category">Category</Label>
                            <Input
                                id="policy-category"
                                value={category}
                                onChange={(event) =>
                                    setCategory(event.target.value)
                                }
                                placeholder="e.g. Travel"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="policy-name">Display name</Label>
                            <Input
                                id="policy-name"
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                placeholder="Optional"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="policy-cap">Cap amount</Label>
                            <Input
                                id="policy-cap"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                value={capAmount}
                                onChange={(event) =>
                                    setCapAmount(event.target.value)
                                }
                                placeholder="Unlimited"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="policy-advance">Advance limit</Label>
                            <Input
                                id="policy-advance"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                value={advanceLimit}
                                onChange={(event) =>
                                    setAdvanceLimit(event.target.value)
                                }
                                placeholder="No limit"
                            />
                        </div>
                    </div>
                    <label className="flex items-center gap-2 text-sm">
                        <input
                            type="checkbox"
                            checked={requiresReceipt}
                            onChange={(event) =>
                                setRequiresReceipt(event.target.checked)
                            }
                            className="size-4 rounded border-border accent-primary"
                        />
                        Require a receipt for claims in this category
                    </label>
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
                            ) : null}
                            Save policy
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function SubmitClaimDialog({
    open,
    onOpenChange,
    onSubmit,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onSubmit: () => void;
}) {
    const setOpen = onOpenChange;
    const [category, setCategory] = useState("");
    const [amount, setAmount] = useState("");
    const [description, setDescription] = useState("");
    const [receiptUrl, setReceiptUrl] = useState("");
    const [advanceAmount, setAdvanceAmount] = useState("");
    const [blocked, setBlocked] = useState<string | null>(null);
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open) {
            setBlocked(null);
            setSubmitError(null);
        }
    }, [open]);

    async function submit() {
        const amountValue = Number(amount);
        const advance =
            advanceAmount.trim() === "" ? null : Number(advanceAmount);
        if (
            !category.trim() ||
            !Number.isFinite(amountValue) ||
            amountValue <= 0
        ) {
            setSubmitError("Enter a category and a positive amount.");
            return;
        }
        setSubmitError(null);
        setSubmitting(true);
        setBlocked(null);
        try {
            await submitExpenseClaim({
                category: category.trim(),
                amount: amountValue,
                description: description.trim() || null,
                receipt_url: receiptUrl.trim() || null,
                advance_amount:
                    advance != null && Number.isFinite(advance) && advance > 0
                        ? advance
                        : null,
            });
            setOpen(false);
            onSubmit();
        } catch (error) {
            if (
                error instanceof ApiError &&
                (error.status === 409 || error.status === 422)
            ) {
                setBlocked(error.message);
            } else {
                setSubmitError(
                    error instanceof ApiError
                        ? error.message
                        : "The claim could not be submitted.",
                );
            }
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogTrigger asChild>
                <Button>
                    <Plus aria-hidden="true" className="size-4" />
                    Submit claim
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <ReceiptText aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>Submit expense claim</DialogTitle>
                        <DialogDescription>
                            The claim is checked against the category policy and
                            is approved instantly when it passes.
                        </DialogDescription>
                    </DialogHeader>
                </div>
                <form
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                    className="space-y-4"
                >
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="claim-category">Category</Label>
                            <Input
                                id="claim-category"
                                value={category}
                                onChange={(event) =>
                                    setCategory(event.target.value)
                                }
                                placeholder="e.g. Travel"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="claim-amount">Amount</Label>
                            <Input
                                id="claim-amount"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                value={amount}
                                onChange={(event) =>
                                    setAmount(event.target.value)
                                }
                            />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="claim-description">Description</Label>
                        <Input
                            id="claim-description"
                            value={description}
                            onChange={(event) =>
                                setDescription(event.target.value)
                            }
                            placeholder="Optional"
                        />
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="claim-receipt">Receipt URL</Label>
                            <Input
                                id="claim-receipt"
                                value={receiptUrl}
                                onChange={(event) =>
                                    setReceiptUrl(event.target.value)
                                }
                                placeholder="Optional"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="claim-advance">Advance amount</Label>
                            <Input
                                id="claim-advance"
                                type="number"
                                inputMode="decimal"
                                min="0"
                                step="0.01"
                                value={advanceAmount}
                                onChange={(event) =>
                                    setAdvanceAmount(event.target.value)
                                }
                                placeholder="Optional"
                            />
                        </div>
                    </div>
                    {blocked ? (
                        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
                            <p className="font-medium text-destructive">
                                Claim blocked
                            </p>
                            <p className="mt-1 text-muted-foreground">
                                {blocked} A policy violation was recorded.
                            </p>
                        </div>
                    ) : null}
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
                            ) : null}
                            Submit
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function ClaimActions({
    claim,
    onChanged,
}: {
    claim: ExpenseClaim;
    onChanged: () => void;
}) {
    const { permissions } = useModuleAccess();
    const canApprove = hasPermission(permissions, "erp.expense.approve");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function decide(approve: boolean) {
        setBusy(true);
        setError(null);
        try {
            if (approve) {
                await approveExpenseClaim(claim.id);
            } else {
                await rejectExpenseClaim(claim.id, "Rejected for policy reasons");
            }
            onChanged();
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "The decision failed. Try again.",
            );
        } finally {
            setBusy(false);
        }
    }

    if (claim.status !== "submitted" || !canApprove) return null;
    return (
        <span className="inline-flex items-center gap-1">
            <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void decide(true)}
            >
                <BadgeCheck aria-hidden="true" className="size-3.5" />
                Approve
            </Button>
            <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void decide(false)}
            >
                <CircleX aria-hidden="true" className="size-3.5" />
                Reject
            </Button>
            {error ? (
                <span
                    role="alert"
                    className="text-xs font-medium text-destructive"
                >
                    {error}
                </span>
            ) : null}
        </span>
    );
}

const policyColumns: FinanceColumn<ExpensePolicy>[] = [
    { label: "Category", render: (policy) => policy.category },
    { label: "Name", render: (policy) => policy.name ?? "-" },
    {
        label: "Cap",
        align: "right",
        render: (policy) =>
            policy.cap_amount != null ? (
                <span className="tabular-nums">
                    {formatMoney(policy.cap_amount)}
                </span>
            ) : (
                <span className="text-muted-foreground">Unlimited</span>
            ),
    },
    {
        label: "Receipt",
        render: (policy) => (
            <StatusBadge tone={policy.requires_receipt ? "warning" : "success"}>
                {policy.requires_receipt ? "Required" : "Optional"}
            </StatusBadge>
        ),
    },
    {
        label: "Advance limit",
        align: "right",
        render: (policy) =>
            policy.advance_limit != null ? (
                <span className="tabular-nums">
                    {formatMoney(policy.advance_limit)}
                </span>
            ) : (
                <span className="text-muted-foreground">No limit</span>
            ),
    },
];

const claimColumns = (onChanged: () => void): FinanceColumn<ExpenseClaim>[] => [
    { label: "Category", render: (claim) => claim.category },
    {
        label: "Amount",
        align: "right",
        render: (claim) => (
            <span className="tabular-nums">{formatMoney(claim.amount)}</span>
        ),
    },
    {
        label: "Advance",
        align: "right",
        render: (claim) =>
            claim.advance_amount != null ? (
                <span className="tabular-nums">
                    {formatMoney(claim.advance_amount)}
                </span>
            ) : (
                <span className="text-muted-foreground">-</span>
            ),
    },
    {
        label: "Status",
        render: (claim) => (
            <StatusBadge tone={claimTone[claim.status]}>
                {claimLabel[claim.status]}
            </StatusBadge>
        ),
    },
    { label: "Submitted", render: (claim) => formatDate(claim.created_at) },
    {
        label: "",
        align: "right",
        render: (claim) => (
            <ClaimActions claim={claim} onChanged={onChanged} />
        ),
    },
];

const violationColumns: FinanceColumn<ExpenseViolation>[] = [
    { label: "Category", render: (violation) => violation.category },
    {
        label: "Reason",
        render: (violation) => (
            <span className="font-mono text-xs">{violation.reason_code}</span>
        ),
    },
    {
        label: "Outcome",
        render: (violation) => (
            <StatusBadge tone="danger">{violation.outcome}</StatusBadge>
        ),
    },
    {
        label: "Amount",
        align: "right",
        render: (violation) => (
            <span className="tabular-nums">{formatMoney(violation.amount)}</span>
        ),
    },
    { label: "Message", render: (violation) => violation.message ?? "-" },
    { label: "Date", render: (violation) => formatDate(violation.created_at) },
];

export function FinanceExpenses() {
    const { permissions } = useModuleAccess();
    const canWrite = hasPermission(permissions, "erp.expense.write");
    const [tab, setTab] = useState<PageTab>("policies");
    const [policies, setPolicies] = useState<ExpensePolicy[]>([]);
    const [claims, setClaims] = useState<ExpenseClaim[]>([]);
    const [violations, setViolations] = useState<ExpenseViolation[]>([]);
    const [status, setStatus] = useState<PoliciesStatus>({ state: "loading" });
    const [query, setQuery] = useState("");
    const [claimTab, setClaimTab] = useState("all");
    const [policyDialogOpen, setPolicyDialogOpen] = useState(false);
    const [claimDialogOpen, setClaimDialogOpen] = useState(false);

    const loadAll = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const [p, c, v] = await Promise.all([
                listExpensePolicies(),
                listExpenseClaims(),
                listExpenseViolations(),
            ]);
            setPolicies(p);
            setClaims(c);
            setViolations(v);
            setStatus({ state: "ready" });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load expense data.",
            });
        }
    }, []);

    useEffect(() => {
        void loadAll();
    }, [loadAll]);

    if (status.state === "loading") {
        return (
            <div className="space-y-6">
                <PageHeader
                    title="Expense Control"
                    description="Category policies, claims, and recorded violations."
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
                    title="Expense Control"
                    description="Category policies, claims, and recorded violations."
                    icon={ReceiptText}
                />
                <FinanceErrorState
                    message={status.message}
                    onRetry={() => void loadAll()}
                />
            </div>
        );
    }

    const needle = query.trim().toLowerCase();
    let rows: ReactNode;

    if (tab === "policies") {
        const visible = policies.filter(
            (policy) =>
                !needle ||
                policy.category.toLowerCase().includes(needle) ||
                (policy.name ?? "").toLowerCase().includes(needle),
        );
        rows = (
            <FinanceTable
                columns={policyColumns}
                rows={visible}
                getKey={(policy) => policy.id}
                footer={
                    <span>
                        {visible.length} of {policies.length} policies
                    </span>
                }
            />
        );
    } else if (tab === "claims") {
        const visible = claims.filter((claim) => {
            if (claimTab !== "all" && claim.status !== claimTab) return false;
            if (!needle) return true;
            return (
                claim.category.toLowerCase().includes(needle) ||
                (claim.description ?? "").toLowerCase().includes(needle)
            );
        });
        rows = (
            <FinanceTable
                columns={claimColumns(loadAll)}
                rows={visible}
                getKey={(claim) => claim.id}
                footer={
                    <span className="flex justify-between gap-4">
                        <span>
                            {visible.length} of {claims.length} claims
                        </span>
                        <span className="tabular-nums">
                            {formatMoney(
                                claims
                                    .filter((c) => c.status === "approved")
                                    .reduce(
                                        (sum, claim) => sum + claim.amount,
                                        0,
                                    ),
                            )}{" "}
                            approved
                        </span>
                    </span>
                }
            />
        );
    } else {
        const visible = violations.filter(
            (violation) =>
                !needle ||
                violation.category.toLowerCase().includes(needle) ||
                violation.reason_code.toLowerCase().includes(needle),
        );
        rows = (
            <FinanceTable
                columns={violationColumns}
                rows={visible}
                getKey={(violation) => violation.id}
                footer={
                    <span>
                        {visible.length} of {violations.length} violations
                    </span>
                }
            />
        );
    }

    return (
        <div className="space-y-6">
            <PageHeader
                title="Expense Control"
                description="Category policies, claims, and recorded violations."
                icon={ReceiptText}
            />
            <TableToolbar
                searchPlaceholder={
                    tab === "policies"
                        ? "Search policies…"
                        : tab === "claims"
                          ? "Search claims…"
                          : "Search violations…"
                }
                searchValue={query}
                onSearchChange={setQuery}
                tabs={[
                    { key: "policies", label: "Policies", count: policies.length },
                    { key: "claims", label: "Claims", count: claims.length },
                    {
                        key: "violations",
                        label: "Violations",
                        count: violations.length,
                    },
                ]}
                activeTab={tab}
                onTabChange={(key) => setTab(key as PageTab)}
                actions={
                    <div className="flex items-center gap-2">
                        {tab === "claims" ? (
                            <div className="inline-flex rounded-lg border border-border bg-card p-0.5">
                                {(["all", "submitted", "approved", "rejected"] as const).map(
                                    (key) => (
                                        <button
                                            key={key}
                                            type="button"
                                            aria-pressed={claimTab === key}
                                            onClick={() => setClaimTab(key)}
                                            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                                                claimTab === key
                                                    ? "bg-primary text-primary-foreground"
                                                    : "text-muted-foreground hover:text-foreground"
                                            }`}
                                        >
                                            {key === "all"
                                                ? "All"
                                                : claimLabel[key]}
                                        </button>
                                    ),
                                )}
                            </div>
                        ) : null}
                        {tab === "policies" && canWrite ? (
                            <PolicyDialog
                                open={policyDialogOpen}
                                onOpenChange={setPolicyDialogOpen}
                                onSaved={() => void loadAll()}
                            />
                        ) : null}
                        {tab === "claims" && canWrite ? (
                            <SubmitClaimDialog
                                open={claimDialogOpen}
                                onOpenChange={setClaimDialogOpen}
                                onSubmit={() => void loadAll()}
                            />
                        ) : null}
                    </div>
                }
            />

            {tab === "policies" && policies.length === 0 ? (
                <FinanceEmptyState
                    icon={ShieldCheck}
                    title="No expense policies yet"
                    description="Add a policy to auto-approve or block claims per category."
                />
            ) : tab === "claims" && claims.length === 0 ? (
                <FinanceEmptyState
                    icon={ReceiptText}
                    title="No expense claims yet"
                    description="Submit a claim to check it against the category policy."
                />
            ) : tab === "violations" && violations.length === 0 ? (
                <FinanceEmptyState
                    icon={ShieldCheck}
                    title="No violations"
                    description="Blocked claims are recorded here once a policy rule is hit."
                />
            ) : (
                rows
            )}
        </div>
    );
}