"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Building2,
  CalendarDays,
  ClipboardList,
  Contact,
  LoaderCircle,
  Mail,
  Phone,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { RelationshipTabs } from "@/components/dashboard/erp/crm/anchor-panels";
import { ErrorState } from "@/components/dashboard/erp/error-state";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useModuleAccess } from "@/lib/access/modules";
import {
  disqualifyLead,
  getLead,
  qualifyLead,
  type Lead,
  type Opportunity,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { LEAD_STATUS_LABELS, leadStatusBadgeClass } from "@/lib/erp/labels";
import { formatDate } from "@/lib/erp/money";
import { setPageTitle } from "@/lib/topbar-title";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; lead: Lead; notice?: string };

interface LeadDetailProps {
  leadId: string;
}

const CURRENCIES = ["USD", "EUR", "GBP"];

function leadName(lead: Lead): string {
  return [lead.firstName, lead.lastName].filter(Boolean).join(" ") || "Unnamed lead";
}

export function LeadDetail({ leadId }: LeadDetailProps) {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [qualifyOpen, setQualifyOpen] = useState(false);
  const [disqualifyOpen, setDisqualifyOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const lead = await getLead(leadId);
      setStatus({ state: "ready", lead });
      setPageTitle(leadName(lead));
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the lead.",
      });
      setPageTitle(null);
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => setPageTitle(null), []);

  async function onDisqualify() {
    setBusy(true);
    try {
      await disqualifyLead(leadId);
      await load();
      setDisqualifyOpen(false);
    } catch (error) {
      setStatus((current) => ({
        ...current,
        notice: error instanceof ApiError ? error.message : "Could not disqualify the lead.",
      }));
    } finally {
      setBusy(false);
    }
  }

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 rounded-lg bg-muted/70" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-64 rounded-xl" />
          <Skeleton className="h-64 rounded-xl lg:col-span-2" />
        </div>
      </div>
    );
  }

  if (status.state === "error") {
    return <ErrorState message={status.message} onRetry={() => void load()} />;
  }

  const { lead } = status;
  const name = leadName(lead);

  return (
    <div className="space-y-4">
      <div>
        <Button type="button" variant="ghost" size="sm" asChild>
          <Link href="/dashboard/erp/crm/leads">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to leads
          </Link>
        </Button>
      </div>

      {status.notice ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
        >
          {status.notice}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="rounded-xl border border-border bg-card p-5 lg:col-span-1">
          <div className="flex items-start justify-between gap-3">
            <div className="flex size-11 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Contact aria-hidden="true" className="size-5" />
            </div>
            {canWrite && lead.status !== "qualified" ? (
              <div className="flex flex-wrap gap-1">
                {lead.status !== "disqualified" ? (
                  <Button type="button" size="sm" onClick={() => setQualifyOpen(true)}>
                    <ClipboardList aria-hidden="true" className="size-4" />
                    Qualify
                  </Button>
                ) : null}
                {lead.status !== "disqualified" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setDisqualifyOpen(true)}
                  >
                    <XCircle aria-hidden="true" className="size-4 text-muted-foreground" />
                    Disqualify
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>

          <h2 className="mt-4 font-display text-lg font-semibold text-foreground">{name}</h2>
          {lead.company ? (
            <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Building2 aria-hidden="true" className="size-3.5" />
              {lead.company}
            </p>
          ) : null}

          <Badge
            variant="outline"
            className={leadStatusBadgeClass(lead.status)}
          >
            {LEAD_STATUS_LABELS[lead.status]}
          </Badge>

          <dl className="mt-5 space-y-3 text-sm">
            {lead.source ? (
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted-foreground">Source</dt>
                <dd className="font-medium text-foreground">{lead.source}</dd>
              </div>
            ) : null}
            {lead.email ? (
              <div className="flex items-center justify-between gap-3">
                <dt className="flex items-center gap-1.5 text-muted-foreground">
                  <Mail aria-hidden="true" className="size-3.5" />
                  Email
                </dt>
                <dd className="truncate font-medium text-foreground">{lead.email}</dd>
              </div>
            ) : null}
            {lead.phone ? (
              <div className="flex items-center justify-between gap-3">
                <dt className="flex items-center gap-1.5 text-muted-foreground">
                  <Phone aria-hidden="true" className="size-3.5" />
                  Phone
                </dt>
                <dd className="font-medium text-foreground">{lead.phone}</dd>
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-1.5 text-muted-foreground">
                <CalendarDays aria-hidden="true" className="size-3.5" />
                Created
              </dt>
              <dd className="font-medium text-foreground">
                {lead.createdAt ? formatDate(lead.createdAt) : "—"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-1.5 text-muted-foreground">
                <CalendarDays aria-hidden="true" className="size-3.5" />
                Updated
              </dt>
              <dd className="font-medium text-foreground">
                {lead.updatedAt ? formatDate(lead.updatedAt) : "—"}
              </dd>
            </div>
          </dl>

          {lead.status === "disqualified" ? (
            <p className="mt-5 rounded-lg border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              This lead is disqualified. Use the leads list if you need to re-qualify later.
            </p>
          ) : null}
        </section>

        <section className="lg:col-span-2">
          <RelationshipTabs
            entityType="lead"
            entityId={leadId}
            canWrite={canWrite && lead.status !== "disqualified"}
          />
        </section>
      </div>

      <QualifyDialog
        leadId={leadId}
        open={qualifyOpen}
        onOpenChange={setQualifyOpen}
        onQualified={(opportunity) => {
          router.push(`/dashboard/erp/crm/opportunities/${opportunity.id}`);
        }}
      />

      <Dialog open={disqualifyOpen} onOpenChange={setDisqualifyOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Disqualify {name}?</DialogTitle>
            <DialogDescription>
              The lead moves to the disqualified state and stays out of the pipeline. You can
              still view it from the leads list later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDisqualifyOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={onDisqualify} disabled={busy}>
              {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Disqualify
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function QualifyDialog({
  leadId,
  open,
  onOpenChange,
  onQualified,
}: {
  leadId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onQualified: (opportunity: Opportunity) => void;
}) {
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [probability, setProbability] = useState("");
  const [expectedClose, setExpectedClose] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setAmount("");
      setCurrency("USD");
      setProbability("");
      setExpectedClose("");
      setSaving(false);
      setNotice(null);
    }
  }, [open]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;

    const probabilityValue = probability ? Number(probability) : 0;
    if (Number.isNaN(probabilityValue) || probabilityValue < 0 || probabilityValue > 100) {
      setNotice("Probability must be a number between 0 and 100.");
      return;
    }

    setSaving(true);
    setNotice(null);
    try {
      const opportunity = await qualifyLead(leadId, {
        amount: amount ? amount : undefined,
        currency,
        probability: probabilityValue,
        expectedCloseDate: expectedClose || undefined,
      });
      onQualified(opportunity);
      onOpenChange(false);
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : "Could not qualify the lead.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClipboardList aria-hidden="true" className="size-4 text-primary" />
            Qualify lead
          </DialogTitle>
          <DialogDescription>
            This creates an opportunity in the first pipeline stage. You can add
            estimated value and target date below.
          </DialogDescription>
        </DialogHeader>

        <form id="qualify-form" onSubmit={(event) => void onSubmit(event)} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="qualify-amount">Expected amount</Label>
              <Input
                id="qualify-amount"
                type="number"
                inputMode="decimal"
                min="0"
                step="0.01"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="e.g. 12000"
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Currency</Label>
              <Select value={currency} onValueChange={setCurrency} disabled={saving}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CURRENCIES.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="qualify-probability">Probability (%)</Label>
              <Input
                id="qualify-probability"
                type="number"
                inputMode="numeric"
                min="0"
                max="100"
                value={probability}
                onChange={(event) => setProbability(event.target.value)}
                placeholder="e.g. 50"
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="qualify-close">Expected close date</Label>
              <Input
                id="qualify-close"
                type="date"
                value={expectedClose}
                onChange={(event) => setExpectedClose(event.target.value)}
                disabled={saving}
              />
            </div>
          </div>

          {notice ? (
            <div
              role="alert"
              className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
            >
              {notice}
            </div>
          ) : null}
        </form>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button type="submit" form="qualify-form" disabled={saving}>
            {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
            Qualify
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
