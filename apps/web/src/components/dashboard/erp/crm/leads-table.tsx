"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, LoaderCircle, Plus, Search, UserPlus, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { Pagination, offsetMeta } from "@/components/dashboard/erp/pagination";
import { LeadFormDialog } from "@/components/dashboard/erp/crm/lead-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { useModuleAccess } from "@/lib/access/modules";
import { cn } from "@/lib/utils";
import {
  disqualifyLead,
  listLeads,
  qualifyLead,
  type Lead,
  type LeadStatus,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { leadActions } from "@/lib/erp/actions";
import { formatDate } from "@/lib/erp/money";
import { leadStatusBadgeClass, LEAD_STATUS_LABELS } from "@/lib/erp/labels";

const PAGE_SIZE = 50;

const STATUS_FILTERS: { value: LeadStatus | "all"; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "qualified", label: "Qualified" },
  { value: "disqualified", label: "Disqualified" },
];

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; leads: Lead[]; total: number; notice?: string };

function leadName(lead: Lead): string {
  const name = [lead.firstName, lead.lastName].filter(Boolean).join(" ");
  return name || lead.company || "Unnamed lead";
}

export function LeadsTable() {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [statusFilter, setStatusFilter] = useState<LeadStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [qualifying, setQualifying] = useState<Lead | null>(null);
  const [disqualifying, setDisqualifying] = useState<Lead | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listLeads({
        status: statusFilter === "all" ? undefined : statusFilter,
        offset,
        limit: PAGE_SIZE,
      });
      setStatus({ state: "ready", leads: result.data, total: result.meta.total });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load leads.";
      setStatus({ state: "error", message });
    }
  }, [statusFilter, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleLeads = useMemo(() => {
    if (status.state !== "ready") return [];
    const term = query.trim().toLowerCase();
    if (!term) return status.leads;
    return status.leads.filter((lead) =>
      [
        lead.firstName,
        lead.lastName,
        lead.company,
        lead.email,
        lead.source,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term)),
    );
  }, [status, query]);

  async function runAction(action: () => Promise<unknown>, leadId: string) {
    setPendingId(leadId);
    try {
      await action();
      await load();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "The action could not be completed.";
      setStatus((current) =>
        current.state === "ready" ? { ...current, notice: message } : current,
      );
    } finally {
      setPendingId(null);
    }
  }

  function onQualifyConfirm(amount: string, probability: number, expectedCloseDate: string) {
    if (!qualifying) return;
    const leadId = qualifying.id;
    void runAction(
      () =>
        qualifyLead(leadId, {
          amount: amount || undefined,
          probability,
          expectedCloseDate: expectedCloseDate || undefined,
        }),
      leadId,
    );
    setQualifying(null);
  }

  function onDisqualifyConfirm() {
    if (!disqualifying) return;
    const leadId = disqualifying.id;
    void runAction(() => disqualifyLead(leadId), leadId);
    setDisqualifying(null);
  }

  const columns: ErpColumn<Lead>[] = [
    {
      key: "name",
      label: "Contact",
      render: (lead) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground">{leadName(lead)}</p>
          {lead.company ? (
            <p className="truncate text-xs text-muted-foreground">{lead.company}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "contact",
      label: "Contact info",
      render: (lead) => (
        <div className="min-w-0">
          <p className="truncate text-foreground">{lead.email || "—"}</p>
          <p className="truncate text-xs text-muted-foreground">{lead.phone || ""}</p>
        </div>
      ),
    },
    {
      key: "source",
      label: "Source",
      render: (lead) => <span className="text-foreground">{lead.source || "—"}</span>,
    },
    {
      key: "status",
      label: "Status",
      render: (lead) => (
        <Badge variant="outline" className={leadStatusBadgeClass(lead.status)}>
          {LEAD_STATUS_LABELS[lead.status]}
        </Badge>
      ),
    },
    {
      key: "created",
      label: "Created",
      render: (lead) => (
        <span className="text-foreground">{formatDate(lead.createdAt)}</span>
      ),
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      className: "w-36",
      render: (lead) => {
        const actions = leadActions(lead.status);
        const pending = pendingId === lead.id;
        return canWrite && (actions.qualify || actions.disqualify) ? (
          <div className="flex items-center justify-end gap-1">
            {actions.qualify ? (
              <Button
                type="button"
                variant="outline"
                size="xs"
                disabled={pendingId !== null}
                onClick={() => setQualifying(lead)}
              >
                {pending ? (
                  <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />
                ) : (
                  <CheckCircle2 aria-hidden="true" className="size-3" />
                )}
                Qualify
              </Button>
            ) : null}
            {actions.disqualify ? (
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Disqualify ${leadName(lead)}`}
                title="Disqualify"
                disabled={pendingId !== null}
                onClick={() => setDisqualifying(lead)}
              >
                <XCircle aria-hidden="true" className="size-3.5 text-muted-foreground" />
              </Button>
            ) : null}
          </div>
        ) : null;
      },
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="h-8 w-40 rounded-lg bg-muted/70" />
            <div className="h-8 w-56 rounded-lg bg-muted/70" />
          </div>
          <div className="h-8 w-24 rounded-lg bg-muted/70" />
        </div>
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="h-8 w-40 rounded-lg bg-muted/70" />
            <div className="h-8 w-56 rounded-lg bg-muted/70" />
          </div>
        </div>
        <ErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <nav
        aria-label="Lead status views"
        role="tablist"
        className="flex items-center gap-1 overflow-x-auto border-b border-border/60"
        style={{ scrollbarWidth: "none" }}
      >
        {STATUS_FILTERS.map((tab) => {
          const active = statusFilter === tab.value;
          return (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => {
                setStatusFilter(tab.value);
                setOffset(0);
              }}
              className={cn(
                "relative inline-flex h-9 shrink-0 items-center px-3 text-sm font-medium transition-colors",
                active
                  ? "font-semibold text-emerald-600 dark:text-emerald-400"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute bottom-0 left-3 right-3 h-[2px] rounded-full bg-emerald-500 dark:bg-emerald-400"
                />
              )}
            </button>
          );
        })}
      </nav>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search
              aria-hidden="true"
              className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-56 pl-8"
              placeholder="Search name, company, email"
              aria-label="Search leads"
            />
          </div>
        </div>
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" className="size-4" />
            New lead
          </Button>
        ) : null}
      </div>

      {status.notice ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
        >
          {status.notice}
        </div>
      ) : null}

      {visibleLeads.length === 0 ? (
        <EmptyState
          icon={UserPlus}
          title={query.trim() || statusFilter !== "all" ? "No matching leads" : "No leads yet"}
          description={
            query.trim() || statusFilter !== "all"
              ? "Try a different search or filter."
              : "Capture your first inbound inquiry to start building a pipeline."
          }
          action={
            canWrite && !query.trim() && statusFilter === "all" ? (
              <Button type="button" variant="outline" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden="true" className="size-4" />
                New lead
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ErpTable
          columns={columns}
          rows={visibleLeads}
          rowKey={(lead) => lead.id}
          onRowClick={(lead) => router.push(`/dashboard/erp/crm/leads/${lead.id}`)}
          footer={
            <Pagination
              meta={offsetMeta(offset, PAGE_SIZE, status.total)}
              onPageChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
            />
          }
        />
      )}

      <LeadFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={() => {
          setOffset(0);
          void load();
        }}
      />

      {/* Qualify dialog — optional enrichment for the opportunity being created. */}
      <Dialog open={qualifying !== null} onOpenChange={(open) => !open && setQualifying(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Qualify {qualifying ? leadName(qualifying) : "lead"}?</DialogTitle>
            <DialogDescription>
              Qualifying creates an opportunity at the prospecting stage. Add deal details below
              (optional — you can edit them later).
            </DialogDescription>
          </DialogHeader>
          <QualifyForm
            key={qualifying?.id ?? "none"}
            busy={pendingId !== null}
            onSubmit={onQualifyConfirm}
            onCancel={() => setQualifying(null)}
          />
        </DialogContent>
      </Dialog>

      {/* Disqualify confirm — terminal dead end for the lead. */}
      <Dialog
        open={disqualifying !== null}
        onOpenChange={(open) => !open && setDisqualifying(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disqualify {disqualifying ? leadName(disqualifying) : "lead"}?</DialogTitle>
            <DialogDescription>
              The lead will be marked disqualified and cannot be qualified later. This cannot be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDisqualifying(null)}
              disabled={pendingId !== null}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={onDisqualifyConfirm}
              disabled={pendingId !== null}
            >
              {pendingId !== null ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <XCircle aria-hidden="true" className="size-4" />
              )}
              Disqualify
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function QualifyForm({
  busy,
  onSubmit,
  onCancel,
}: {
  busy: boolean;
  onSubmit: (amount: string, probability: number, expectedCloseDate: string) => void;
  onCancel: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [probability, setProbability] = useState("20");
  const [expectedCloseDate, setExpectedCloseDate] = useState("");

  const probabilityValue = Math.max(0, Math.min(100, Number(probability) || 0));

  return (
    <form
      id="qualify-form"
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(amount.trim(), probabilityValue, expectedCloseDate);
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="qualify-amount">Amount</Label>
          <Input
            id="qualify-amount"
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="0.00"
            disabled={busy}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="qualify-probability">Probability (%)</Label>
          <Input
            id="qualify-probability"
            type="number"
            min="0"
            max="100"
            value={probability}
            onChange={(event) => setProbability(event.target.value)}
            disabled={busy}
          />
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="qualify-close">Expected close date</Label>
        <Input
          id="qualify-close"
          type="date"
          value={expectedCloseDate}
          onChange={(event) => setExpectedCloseDate(event.target.value)}
          disabled={busy}
        />
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" form="qualify-form" disabled={busy}>
          {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
          Qualify
        </Button>
      </DialogFooter>
    </form>
  );
}
