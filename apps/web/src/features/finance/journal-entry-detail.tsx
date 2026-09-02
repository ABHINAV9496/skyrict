"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, LoaderCircle, NotebookPen } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import { Button } from "@/components/ui/button";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { hasPermission, useModuleAccess } from "@/lib/access/modules";
import {
  getJournalEntry,
  listAccounts,
  postJournalEntry,
  reverseJournalEntry,
  voidJournalEntry,
  type Account,
  type JournalEntry,
} from "@/lib/api/finance-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatDateTime, formatMoney, sumMoney } from "@/lib/finance/format";
import { cn } from "@/lib/utils";
import { FinanceTable, type FinanceColumn } from "@/features/finance/components/finance-table";
import { EntryStatusBadge } from "@/features/finance/components/status-badge";
import { FinanceErrorState } from "@/features/finance/components/state-cards";

type BusyAction = "post" | "void" | "reverse";

type Status =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; entry: JournalEntry; accounts: Account[]; busy: BusyAction | null };

export function JournalEntryDetail({ entryId }: { entryId: string }) {
  const { permissions } = useModuleAccess();
  const canWrite = hasPermission(permissions, "erp.finance.write");
  const canApprove = hasPermission(permissions, "erp.finance.approve");
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [entry, accounts] = await Promise.all([getJournalEntry(entryId), listAccounts(true)]);
      setStatus({ state: "ready", entry, accounts, busy: null });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the journal entry.",
      });
    }
  }, [entryId]);

  useEffect(() => {
    void load();
  }, [load]);

  const accountById = useMemo(() => {
    const map = new Map<string, Account>();
    if (status.state === "ready") {
      for (const account of status.accounts) map.set(account.id, account);
    }
    return map;
  }, [status]);

  async function runAction(action: "post" | "void" | "reverse") {
    if (status.state !== "ready" || status.busy !== null) return;
    if (action === "void" && !window.confirm("Void this draft entry? This cannot be undone.")) {
      return;
    }
    if (
      action === "reverse" &&
      !window.confirm(
        "Reverse this posted entry? A reversing entry with opposite debits and credits will be created.",
      )
    ) {
      return;
    }
    setActionError(null);
    setStatus({ ...status, busy: action });
    try {
      if (action === "post") await postJournalEntry(entryId);
      else if (action === "void") await voidJournalEntry(entryId);
      else await reverseJournalEntry(entryId);
      await load();
    } catch (error) {
      setActionError(
        error instanceof ApiError ? error.message : "The action could not be completed.",
      );
      setStatus({ ...status, busy: null });
    }
  }

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Journal entry"
          description="General ledger detail."
          icon={NotebookPen}
        />
        <TableSkeleton rows={5} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Journal entry"
          description="General ledger detail."
          icon={NotebookPen}
        />
        <FinanceErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  const { entry } = status;
  const totalDebit = sumMoney(entry.lines.map((line) => line.debit));
  const totalCredit = sumMoney(entry.lines.map((line) => line.credit));
  const balanced = totalDebit === totalCredit;

  const columns: FinanceColumn<JournalEntry["lines"][number]>[] = [
    {
      label: "Account",
      render: (line) => {
        const account = accountById.get(line.account_id);
        return account ? `${account.code} · ${account.name}` : "Unknown account";
      },
    },
    { label: "Debit", align: "right", render: (line) => formatMoney(line.debit) },
    { label: "Credit", align: "right", render: (line) => formatMoney(line.credit) },
  ];

  const canPost = entry.status === "draft" && canApprove;
  const canVoid = entry.status === "draft" && canWrite;
  const canReverse = entry.status === "posted" && entry.reversal_entry_id === null && canApprove;

  return (
    <div className="space-y-6">
      <Link
        href="/dashboard/erp/finance/journal-entries"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Journal entries
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">Journal entry</p>
          <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-foreground">
            {entry.memo ?? "No memo"}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <EntryStatusBadge status={entry.status} />
          {canPost ? (
            <Button
              type="button"
              disabled={status.busy !== null}
              onClick={() => void runAction("post")}
            >
              {status.busy === "post" ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Post
            </Button>
          ) : null}
          {canVoid ? (
            <Button
              type="button"
              variant="outline"
              disabled={status.busy !== null}
              onClick={() => void runAction("void")}
            >
              {status.busy === "void" ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Void
            </Button>
          ) : null}
          {canReverse ? (
            <Button
              type="button"
              variant="outline"
              disabled={status.busy !== null}
              onClick={() => void runAction("reverse")}
            >
              {status.busy === "reverse" ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Reverse
            </Button>
          ) : null}
        </div>
      </div>

      {actionError ? (
        <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm font-medium text-destructive">
          {actionError}
        </p>
      ) : null}

      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Date</dt>
          <dd className="mt-1 text-sm font-medium text-foreground">{formatDate(entry.entry_date)}</dd>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Source</dt>
          <dd className="mt-1 text-sm font-medium text-foreground">{entry.source}</dd>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">Created</dt>
          <dd className="mt-1 text-sm font-medium text-foreground">{formatDateTime(entry.created_at)}</dd>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <dt className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
            {entry.status === "posted" ? "Posted" : entry.status === "voided" ? "Voided" : "Status"}
          </dt>
          <dd className="mt-1 text-sm font-medium text-foreground">
            {entry.status === "posted" && entry.posted_at
              ? formatDateTime(entry.posted_at)
              : entry.status === "voided" && entry.voided_at
                ? formatDateTime(entry.voided_at)
                : entry.status}
          </dd>
        </div>
      </dl>

      <FinanceTable
        columns={columns}
        rows={entry.lines}
        getKey={(line) => line.id}
        footer={
          <span className="flex items-center justify-between gap-4">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 text-xs font-medium",
                balanced
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-destructive",
              )}
            >
              {balanced ? "Balanced" : "Out of balance"}
            </span>
            <span className="space-y-0.5 text-right">
              <span className="flex justify-between gap-8">
                <span className="text-muted-foreground">Debit</span>
                <span className="font-medium tabular-nums text-foreground">{formatMoney(totalDebit)}</span>
              </span>
              <span className="flex justify-between gap-8">
                <span className="text-muted-foreground">Credit</span>
                <span className="font-medium tabular-nums text-foreground">{formatMoney(totalCredit)}</span>
              </span>
            </span>
          </span>
        }
      />
    </div>
  );
}
