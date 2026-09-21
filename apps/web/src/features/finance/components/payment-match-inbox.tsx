"use client";

import { Spinner } from "@/components/ui/spinner";
import { useCallback, useEffect, useState } from "react";
import { Check, Mail, Undo2, XCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useModuleAccess, hasPermission } from "@/lib/access/modules";
import {
    listPaymentIntents,
    acceptPaymentIntent,
    undoPaymentIntent,
    dismissPaymentIntent,
    type PaymentIntent,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatMoney } from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import { StatusBadge } from "@/features/finance/components/status-badge";
import { FinanceEmptyState } from "@/features/finance/components/state-cards";
import { RecordPaymentDialog } from "@/features/finance/components/record-payment-dialog";

const UNRESOLVED_STATUSES = new Set(["open", "candidate"]);

function IntentStatusBadge({ status }: { status: string }) {
    const tone =
        status === "open"
            ? ("muted" as const)
            : status === "candidate"
              ? ("info" as const)
              : status === "applied"
                ? ("success" as const)
                : ("danger" as const);
    return (
        <StatusBadge tone={tone}>
            {status === "open"
                ? "Unmatched"
                : status === "candidate"
                  ? "Suggested"
                  : status === "applied"
                    ? "Applied"
                    : "Dismissed"}
        </StatusBadge>
    );
}

export function PaymentMatchInbox() {
    const { permissions } = useModuleAccess();
    const canRead = hasPermission(permissions, "erp.finance.read");
    const canWrite = hasPermission(permissions, "erp.finance.write");
    const [intents, setIntents] = useState<PaymentIntent[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const result = await listPaymentIntents({ limit: 50 });
            const unresolved = (result.data ?? []).filter((i) =>
                UNRESOLVED_STATUSES.has(i.status),
            );
            setIntents(unresolved);
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "Could not load payment inbox.",
            );
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (canRead) void load();
    }, [canRead, load]);

    async function handleAccept(intent: PaymentIntent, invoiceId: string) {
        setBusy(true);
        try {
            await acceptPaymentIntent(intent.id, invoiceId);
            await load();
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "Could not accept the match.",
            );
        } finally {
            setBusy(false);
        }
    }

    async function handleUndo(intent: PaymentIntent) {
        setBusy(true);
        try {
            await undoPaymentIntent(intent.id);
            await load();
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "Could not undo — the 15-minute window may have passed.",
            );
        } finally {
            setBusy(false);
        }
    }

    async function handleDismiss(intent: PaymentIntent) {
        setBusy(true);
        try {
            await dismissPaymentIntent(intent.id);
            await load();
        } catch (err) {
            setError(
                err instanceof ApiError
                    ? err.message
                    : "Could not dismiss the receipt.",
            );
        } finally {
            setBusy(false);
        }
    }

    if (!canRead) return null;

    if (loading) {
        return (
            <div className="rounded-lg border border-border bg-card p-4">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Spinner
                        aria-hidden="true"
                        className="size-4"
                    />
                    Loading payment inbox…
                </div>
            </div>
        );
    }

    const columns: FinanceColumn<PaymentIntent>[] = [
        { label: "Reference", render: (i) => i.reference ?? "—" },
        {
            label: "Amount",
            align: "right",
            render: (i) => formatMoney(Number(i.amount)),
        },
        { label: "Customer", render: (i) => i.customer_name ?? "—" },
        {
            label: "Status",
            render: (i) => <IntentStatusBadge status={i.status} />,
        },
        {
            label: "Suggested invoice",
            render: (i) => {
                const top = i.suggestions[0];
                if (!top) {
                    return (
                        <span className="text-muted-foreground">
                            No matches found
                        </span>
                    );
                }
                return (
                    <span className="text-sm">
                        <span className="font-medium">
                            {top.invoice_number}
                        </span>
                        <span className="ml-1 text-muted-foreground">
                            ({formatMoney(Number(top.outstanding))})
                        </span>
                        {top.customer_name ? (
                            <span className="ml-1 text-xs text-muted-foreground">
                                · {top.customer_name}
                            </span>
                        ) : null}
                    </span>
                );
            },
        },
        {
            label: "Score",
            align: "right",
            render: (i) =>
                i.score != null ? `${Math.round(Number(i.score) * 100)}%` : "—",
        },
        {
            label: "",
            align: "right",
            render: (i) => {
                const canAccept =
                    i.status === "candidate" && i.suggestions.length > 0;
                const canUndo = i.status === "applied" && i.applied_at != null;
                return (
                    <div className="flex items-center justify-end gap-1">
                        {canAccept ? (
                            <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                disabled={busy}
                                onClick={() =>
                                    void handleAccept(
                                        i,
                                        i.suggestions[0].invoice_id,
                                    )
                                }
                                title={`Accept: apply to ${i.suggestions[0].invoice_number}`}
                            >
                                <Check
                                    aria-hidden="true"
                                    className="size-3.5"
                                />
                                Accept
                            </Button>
                        ) : null}
                        {canUndo ? (
                            <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                disabled={busy}
                                onClick={() => void handleUndo(i)}
                                title="Undo within 15 minutes"
                            >
                                <Undo2
                                    aria-hidden="true"
                                    className="size-3.5"
                                />
                                Undo
                            </Button>
                        ) : null}
                        <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => void handleDismiss(i)}
                            title="Dismiss this receipt"
                        >
                            <XCircle aria-hidden="true" className="size-3.5" />
                        </Button>
                    </div>
                );
            },
        },
    ];

    return (
        <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-3 flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Mail
                        aria-hidden="true"
                        className="size-4 text-muted-foreground"
                    />
                    <h3 className="text-sm font-medium text-foreground">
                        Payment Inbox
                    </h3>
                    {intents.length > 0 ? (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                            {intents.length}
                        </span>
                    ) : null}
                </div>
                <div className="flex items-center gap-2">
                    {canWrite ? (
                        <RecordPaymentDialog onRecorded={() => void load()} />
                    ) : null}
                    <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => void load()}
                    >
                        Refresh
                    </Button>
                </div>
            </div>

            {error ? (
                <p
                    role="alert"
                    className="mb-3 text-xs font-medium text-destructive"
                >
                    {error}
                </p>
            ) : null}

            {intents.length === 0 ? (
                <FinanceEmptyState
                    icon={Mail}
                    title="No unmatched receipts"
                    description="Incoming payments will appear here once they lack a clear invoice match."
                />
            ) : (
                <FinanceTable
                    columns={columns}
                    rows={intents}
                    getKey={(i) => i.id}
                    footer={`${intents.length} unresolved receipt${intents.length === 1 ? "" : "s"}`}
                />
            )}
        </div>
    );
}
