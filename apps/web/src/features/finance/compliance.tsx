"use client";

import { useCallback, useEffect, useState } from "react";
import {
    BellRing,
    CircleCheck,
    CircleDot,
    LoaderCircle,
    Plus,
    ShieldAlert,
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
    completeComplianceItem,
    createComplianceItem,
    listComplianceItems,
    listComplianceUpcoming,
    type ComplianceItem,
    type ComplianceRecurrence,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate } from "@/lib/finance/format";
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
    | { state: "ready"; items: ComplianceItem[] };

const recurrenceLabel: Record<ComplianceRecurrence | "once", string> = {
    once: "Once",
    monthly: "Monthly",
    quarterly: "Quarterly",
    yearly: "Yearly",
};

function CreateComplianceDialog({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    onCreated: () => void;
}) {
    const setOpen = onOpenChange;
    const [title, setTitle] = useState("");
    const [dueOn, setDueOn] = useState(new Date().toISOString().slice(0, 10));
    const [description, setDescription] = useState("");
    const [recurrence, setRecurrence] = useState<
        ComplianceRecurrence | ""
    >("");
    const [leadDays, setLeadDays] = useState("7");
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        if (open) {
            setSubmitError(null);
        }
    }, [open]);

    async function submit() {
        if (!title.trim() || !dueOn) {
            setSubmitError("A title and due date are required.");
            return;
        }
        const lead = Number(leadDays);
        setSubmitError(null);
        setSubmitting(true);
        try {
            await createComplianceItem({
                title: title.trim(),
                due_on: dueOn,
                description: description.trim() || null,
                recurrence: recurrence || null,
                lead_days: Number.isInteger(lead) && lead >= 0 ? lead : 7,
            });
            setOpen(false);
            onCreated();
        } catch (error) {
            setSubmitError(
                error instanceof ApiError
                    ? error.message
                    : "The compliance item could not be created.",
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
                    New item
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
                <div className="flex items-start gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                        <ShieldAlert aria-hidden="true" className="size-5" />
                    </div>
                    <DialogHeader>
                        <DialogTitle>New compliance item</DialogTitle>
                        <DialogDescription>
                            Track statutory and internal obligations with due
                            dates and optional recurrence.
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
                    <div className="space-y-1.5">
                        <Label htmlFor="compliance-title">Title</Label>
                        <Input
                            id="compliance-title"
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            placeholder="e.g. File VAT return"
                        />
                    </div>
                    <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label htmlFor="compliance-due">Due on</Label>
                            <Input
                                id="compliance-due"
                                type="date"
                                value={dueOn}
                                onChange={(event) =>
                                    setDueOn(event.target.value)
                                }
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="compliance-recurrence">
                                Recurrence
                            </Label>
                            <select
                                id="compliance-recurrence"
                                value={recurrence}
                                onChange={(event) =>
                                    setRecurrence(
                                        event.target
                                            .value as ComplianceRecurrence | "",
                                    )
                                }
                                className="flex h-10 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                            >
                                <option value="">Once</option>
                                <option value="monthly">Monthly</option>
                                <option value="quarterly">Quarterly</option>
                                <option value="yearly">Yearly</option>
                            </select>
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="compliance-description">
                            Description
                        </Label>
                        <Input
                            id="compliance-description"
                            value={description}
                            onChange={(event) =>
                                setDescription(event.target.value)
                            }
                            placeholder="Optional"
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="compliance-lead">
                            Reminder lead (days)
                        </Label>
                        <Input
                            id="compliance-lead"
                            type="number"
                            inputMode="numeric"
                            min="0"
                            max="365"
                            value={leadDays}
                            onChange={(event) => setLeadDays(event.target.value)}
                        />
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
                            ) : null}
                            Save item
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    );
}

function CompleteAction({
    item,
    onChanged,
}: {
    item: ComplianceItem;
    onChanged: () => void;
}) {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState<string | null>(null);

    async function complete() {
        setBusy(true);
        setError(null);
        try {
            await completeComplianceItem(item.id);
            onChanged();
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "The item could not be completed.",
            );
        } finally {
            setBusy(false);
        }
    }

    if (item.status === "completed") return null;
    return (
        <span className="inline-flex items-center gap-2">
            <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void complete()}
            >
                {busy ? (
                    <LoaderCircle
                        aria-hidden="true"
                        className="size-3.5 animate-spin"
                    />
                ) : (
                    <CircleDot aria-hidden="true" className="size-3.5" />
                )}
                Complete
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

const complianceColumns = (onChanged: () => void): FinanceColumn<ComplianceItem>[] => [
    {
        label: "Obligation",
        render: (item) => (
            <span className="flex items-center gap-2">
                {item.title}
                {item.overdue ? (
                    <StatusBadge tone="danger">Overdue</StatusBadge>
                ) : null}
            </span>
        ),
    },
    {
        label: "Due on",
        render: (item) => (
            <span
                className={`tabular-nums ${
                    item.overdue ? "font-medium text-destructive" : ""
                }`}
            >
                {formatDate(item.due_on)}
            </span>
        ),
    },
    {
        label: "Recurrence",
        render: (item) => (
            <span className="capitalize">
                {recurrenceLabel[item.recurrence ?? "once"]}
            </span>
        ),
    },
    {
        label: "Lead",
        align: "right",
        render: (item) => (
            <span className="tabular-nums">{item.lead_days}d</span>
        ),
    },
    {
        label: "Status",
        render: (item) => (
            <StatusBadge tone={item.status === "completed" ? "success" : "warning"}>
                {item.status === "completed" ? "Completed" : "Open"}
            </StatusBadge>
        ),
    },
    {
        label: "Completed",
        render: (item) =>
            item.completed_at ? formatDate(item.completed_at) : "-",
    },
    {
        label: "",
        align: "right",
        render: (item) => <CompleteAction item={item} onChanged={onChanged} />,
    },
];

export function FinanceCompliance() {
    const { permissions } = useModuleAccess();
    const canWrite = hasPermission(permissions, "erp.compliance.write");
    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [query, setQuery] = useState("");
    const [statusTab, setStatusTab] = useState("all");
    const [createOpen, setCreateOpen] = useState(false);
    const [upcoming, setUpcoming] = useState<ComplianceItem[]>([]);

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const [items, nextDue] = await Promise.all([
                listComplianceItems(),
                listComplianceUpcoming(14),
            ]);
            setStatus({ state: "ready", items });
            setUpcoming(nextDue);
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load compliance items.",
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
                    title="Compliance Calendar"
                    description="Statutory and internal obligations with due dates and reminders."
                    icon={ShieldAlert}
                />
                <TableSkeleton rows={6} />
            </div>
        );
    }

    if (status.state === "error") {
        return (
            <div className="space-y-6">
                <PageHeader
                    title="Compliance Calendar"
                    description="Statutory and internal obligations with due dates and reminders."
                    icon={ShieldAlert}
                />
                <FinanceErrorState
                    message={status.message}
                    onRetry={() => void load()}
                />
            </div>
        );
    }

    const needle = query.trim().toLowerCase();
    const visibleItems = status.items.filter((item) => {
        if (statusTab !== "all" && item.status !== statusTab) return false;
        if (!needle) return true;
        return (
            item.title.toLowerCase().includes(needle) ||
            (item.obligation_type ?? "").toLowerCase().includes(needle)
        );
    });

    const overdueCount = status.items.filter((item) => item.overdue).length;

    return (
        <div className="space-y-6">
            <PageHeader
                title="Compliance Calendar"
                description="Statutory and internal obligations with due dates and reminders."
                icon={ShieldAlert}
            />
            <div className="flex flex-wrap gap-3 text-sm">
                <div className="rounded-lg border border-border bg-card px-4 py-2.5">
                    <span className="text-muted-foreground">Overdue </span>
                    <span className="font-semibold tabular-nums text-destructive">
                        {overdueCount}
                    </span>
                </div>
                <div className="rounded-lg border border-border bg-card px-4 py-2.5">
                    <span className="text-muted-foreground">
                        Due in the next 14 days{" "}
                    </span>
                    <span className="font-semibold tabular-nums">
                        {upcoming.length}
                    </span>
                </div>
            </div>
            {upcoming.length > 0 ? (
                <div className="space-y-2 rounded-xl border border-border bg-card p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                        <BellRing aria-hidden="true" className="size-4 text-primary" />
                        Upcoming reminders
                    </div>
                    <ul className="space-y-1.5">
                        {upcoming.map((item) => (
                            <li
                                key={item.id}
                                className="flex items-center justify-between gap-3 rounded-lg bg-muted/40 px-3 py-2 text-sm"
                            >
                                <span className="min-w-0 truncate">
                                    {item.title}
                                </span>
                                <span className="flex shrink-0 items-center gap-2">
                                    {item.overdue ? (
                                        <StatusBadge tone="danger">Overdue</StatusBadge>
                                    ) : null}
                                    <span className="tabular-nums text-muted-foreground">
                                        {formatDate(item.due_on)}
                                    </span>
                                </span>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
            <TableToolbar
                searchPlaceholder="Search obligations…"
                searchValue={query}
                onSearchChange={setQuery}
                tabs={[
                    { key: "all", label: "All", count: status.items.length },
                    {
                        key: "open",
                        label: "Open",
                        count: status.items.filter((i) => i.status === "open")
                            .length,
                    },
                    {
                        key: "completed",
                        label: "Completed",
                        count: status.items.filter(
                            (i) => i.status === "completed",
                        ).length,
                    },
                ]}
                activeTab={statusTab}
                onTabChange={setStatusTab}
                actions={
                    canWrite ? (
                        <CreateComplianceDialog
                            open={createOpen}
                            onOpenChange={setCreateOpen}
                            onCreated={() => void load()}
                        />
                    ) : null
                }
            />

            {visibleItems.length === 0 ? (
                <FinanceEmptyState
                    icon={ShieldAlert}
                    title="No compliance items yet"
                    description="Add an obligation to start tracking due dates and reminders."
                />
            ) : (
                <FinanceTable
                    columns={complianceColumns(load)}
                    rows={visibleItems}
                    getKey={(item) => item.id}
                    footer={
                        <span className="flex items-center gap-4">
                            <CircleCheck
                                aria-hidden="true"
                                className="size-4 text-emerald-500"
                            />
                            <span>
                                {visibleItems.length} of {status.items.length}{" "}
                                obligations
                            </span>
                        </span>
                    }
                />
            )}
        </div>
    );
}