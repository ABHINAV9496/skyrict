"use client";

import { useCallback, useEffect, useState } from "react";
import { Download, ScrollText, Search } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/http";
import { searchAuditLog, type AuditLogEntry } from "@/lib/api/finance-api";
import { formatDateTime } from "@/lib/finance/format";
import {
    FinanceTable,
    type FinanceColumn,
} from "@/features/finance/components/finance-table";
import { FinanceErrorState } from "@/features/finance/components/state-cards";

const PAGE_SIZE = 50;

interface PageState {
    entries: AuditLogEntry[];
    total: number;
    offset: number;
}

type Status =
    | { state: "loading" }
    | { state: "error"; message: string }
    | { state: "ready"; page: PageState };

function entryColumns(): FinanceColumn<AuditLogEntry>[] {
    return [
        { label: "When", render: (entry) => formatDateTime(entry.created_at) },
        { label: "Action", render: (entry) => entry.action },
        {
            label: "Target",
            cellClassName: "max-w-[280px] truncate",
            render: (entry) => (
                <code className="font-mono text-xs">{entry.target}</code>
            ),
        },
        {
            label: "Actor",
            render: (entry) => entry.actor_user_id?.slice(0, 8) ?? "system",
        },
    ];
}

function exportCsv(entries: AuditLogEntry[]): void {
    if (entries.length === 0) return;
    const header = [
        "created_at",
        "action",
        "target",
        "actor_user_id",
        "ip_address",
        "hash",
    ];
    const escape = (value: unknown): string => {
        const text = value == null ? "" : String(value);
        return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    };
    const lines = [
        header.join(","),
        ...entries.map((entry) =>
            [
                entry.created_at,
                entry.action,
                entry.target,
                entry.actor_user_id,
                entry.ip_address,
                entry.hash,
            ]
                .map(escape)
                .join(","),
        ),
    ];
    const blob = new Blob([lines.join("\n")], {
        type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `skyrict-audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

export function FinanceAuditLog() {
    const [status, setStatus] = useState<Status>({ state: "loading" });
    const [query, setQuery] = useState("");
    const [debouncedQuery, setDebouncedQuery] = useState("");
    const [offset, setOffset] = useState(0);

    const load = useCallback(async () => {
        setStatus({ state: "loading" });
        try {
            const result = await searchAuditLog({
                q: debouncedQuery || undefined,
                offset,
                limit: PAGE_SIZE,
            });
            setStatus({
                state: "ready",
                page: {
                    entries: result.entries,
                    total: result.total,
                    offset: result.offset,
                },
            });
        } catch (error) {
            setStatus({
                state: "error",
                message:
                    error instanceof ApiError
                        ? error.message
                        : "Could not load the audit log.",
            });
        }
    }, [debouncedQuery, offset]);

    useEffect(() => {
        const timer = window.setTimeout(() => setDebouncedQuery(query), 350);
        return () => window.clearTimeout(timer);
    }, [query]);

    useEffect(() => {
        setOffset(0);
    }, [debouncedQuery]);

    useEffect(() => {
        void load();
    }, [load]);

    const page = status.state === "ready" ? status.page : null;
    const hasPrev = (page?.offset ?? 0) > 0;
    const hasNext = page
        ? page.offset + page.entries.length < page.total
        : false;

    return (
        <div className="space-y-6">
            <PageHeader
                title="Audit log"
                description="Immutable, tamper-evident trail of ERP actions for this tenant."
                icon={ScrollText}
            />

            <div className="flex flex-wrap items-center gap-3">
                <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
                    <Search
                        aria-hidden="true"
                        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                    />
                    <Input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="Search action or target…"
                        className="pl-9"
                        aria-label="Search audit log"
                    />
                </div>
                <Button
                    type="button"
                    variant="outline"
                    disabled={!page || page.entries.length === 0}
                    onClick={() => page && exportCsv(page.entries)}
                >
                    <Download aria-hidden="true" className="size-4" />
                    Export
                </Button>
            </div>

            {status.state === "error" ? (
                <FinanceErrorState
                    message={status.message}
                    onRetry={() => void load()}
                />
            ) : status.state === "loading" ? (
                <p className="text-sm text-muted-foreground">
                    Loading audit trail…
                </p>
            ) : (
                <FinanceTable
                    columns={entryColumns()}
                    rows={status.page.entries}
                    getKey={(entry) =>
                        entry.id ?? `${entry.created_at}-${entry.target}`
                    }
                    subtitle={
                        <span className="text-muted-foreground">
                            {status.page.total} event(s)
                            {debouncedQuery
                                ? ` matching "${debouncedQuery}"`
                                : ""}
                        </span>
                    }
                    emptyMessage="No audit events found."
                    footer={
                        <div className="flex items-center justify-between">
                            <span className="text-muted-foreground">
                                {status.page.entries.length === 0
                                    ? ""
                                    : `Showing ${status.page.offset + 1}–${status.page.offset + status.page.entries.length} of ${status.page.total}`}
                            </span>
                            <div className="flex items-center gap-2">
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    disabled={!hasPrev}
                                    onClick={() =>
                                        setOffset((value) =>
                                            Math.max(0, value - PAGE_SIZE),
                                        )
                                    }
                                >
                                    Previous
                                </Button>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    disabled={!hasNext}
                                    onClick={() =>
                                        setOffset((value) => value + PAGE_SIZE)
                                    }
                                >
                                    Next
                                </Button>
                            </div>
                        </div>
                    }
                />
            )}
        </div>
    );
}
