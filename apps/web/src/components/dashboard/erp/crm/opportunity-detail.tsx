"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Banknote,
  CalendarDays,
  LoaderCircle,
  Target,
  TrendingUp,
} from "lucide-react";
import Link from "next/link";

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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { useModuleAccess } from "@/lib/access/modules";
import {
  changeOpportunityStage,
  getOpportunity,
  type Opportunity,
  type OpportunityStage,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { isTerminalStage, nextStages, PIPELINE_STAGES } from "@/lib/erp/actions";
import {
  opportunityStageBadgeClass,
  OPPORTUNITY_STAGE_LABELS,
} from "@/lib/erp/labels";
import { formatDate, formatMoney } from "@/lib/erp/money";
import { setPageTitle } from "@/lib/topbar-title";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; opportunity: Opportunity; notice?: string };

interface OpportunityDetailProps {
  opportunityId: string;
}

export function OpportunityDetail({ opportunityId }: OpportunityDetailProps) {
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [pendingStage, setPendingStage] = useState<OpportunityStage | null>(null);
  const [lostReason, setLostReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const opportunity = await getOpportunity(opportunityId);
      setStatus({ state: "ready", opportunity });
      setPageTitle(opportunity.name);
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the opportunity.",
      });
      setPageTitle(null);
    }
  }, [opportunityId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => setPageTitle(null), []);

  async function onConfirmStage() {
    if (!pendingStage || busy) return;
    setBusy(true);
    try {
      await changeOpportunityStage(
        opportunityId,
        pendingStage,
        pendingStage === "lost" && lostReason.trim() ? lostReason.trim() : undefined,
      );
      setPendingStage(null);
      setLostReason("");
      await load();
    } catch (error) {
      setStatus((current) => ({
        ...current,
        notice:
          error instanceof ApiError ? error.message : "Could not move the opportunity.",
      }));
      setPendingStage(null);
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

  const { opportunity } = status;
  const stageIndex = PIPELINE_STAGES.indexOf(opportunity.stage);
  const stages = nextStages(opportunity.stage);

  return (
    <div className="space-y-4">
      <div>
        <Button type="button" variant="ghost" size="sm" asChild>
          <Link href="/dashboard/erp/crm/opportunities">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to pipeline
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
              <TrendingUp aria-hidden="true" className="size-5" />
            </div>
            {canWrite && stages.length > 0 ? (
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">Move to</Label>
                <Select
                  value=""
                  onValueChange={(stage) => {
                    const target = stage as OpportunityStage;
                    if (target === "won" || target === "lost") {
                      setLostReason("");
                      setPendingStage(target);
                    } else {
                      void changeOpportunityStage(opportunityId, target)
                        .then(async () => {
                          await load();
                        })
                        .catch((error: unknown) => {
                          setStatus((current) => ({
                            ...current,
                            notice:
                              error instanceof ApiError
                                ? error.message
                                : "Could not move the opportunity.",
                          }));
                        });
                    }
                  }}
                >
                  <SelectTrigger className="w-44" aria-label="Change stage">
                    <SelectValue placeholder="Choose stage…" />
                  </SelectTrigger>
                  <SelectContent>
                    {stages.map((stage) => (
                      <SelectItem key={stage} value={stage}>
                        {OPPORTUNITY_STAGE_LABELS[stage]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
          </div>

          <h2 className="mt-4 font-display text-lg font-semibold text-foreground">
            {opportunity.name}
          </h2>
          <Badge variant="outline" className={opportunityStageBadgeClass(opportunity.stage)}>
            {OPPORTUNITY_STAGE_LABELS[opportunity.stage]}
          </Badge>

          <div className="mt-5">
            <div
              aria-hidden="true"
              className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted"
            >
              {PIPELINE_STAGES.map((stage) => {
                const active = PIPELINE_STAGES.indexOf(stage) <= stageIndex;
                return (
                  <span
                    key={stage}
                    className={active ? "flex-1 bg-primary/70" : "flex-1 bg-muted"}
                  />
                );
              })}
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">
              Stage {stageIndex + 1} of {PIPELINE_STAGES.length}
            </p>
          </div>

          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-1.5 text-muted-foreground">
                <Banknote aria-hidden="true" className="size-3.5" />
                Value
              </dt>
              <dd className="font-medium text-foreground tabular-nums">
                {opportunity.amount
                  ? formatMoney(opportunity.amount, opportunity.currency ?? "USD")
                  : "-"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-1.5 text-muted-foreground">
                <Target aria-hidden="true" className="size-3.5" />
                Probability
              </dt>
              <dd className="font-medium text-foreground tabular-nums">
                {opportunity.probability}%
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="flex items-center gap-1.5 text-muted-foreground">
                <CalendarDays aria-hidden="true" className="size-3.5" />
                Expected close
              </dt>
              <dd className="font-medium text-foreground">
                {opportunity.expectedCloseDate ? formatDate(opportunity.expectedCloseDate) : "-"}
              </dd>
            </div>
            {opportunity.wonAt ? (
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted-foreground">Won</dt>
                <dd className="font-medium text-foreground">{formatDate(opportunity.wonAt)}</dd>
              </div>
            ) : null}
            {opportunity.lostAt ? (
              <div className="flex items-center justify-between gap-3">
                <dt className="text-muted-foreground">Lost</dt>
                <dd className="font-medium text-foreground">{formatDate(opportunity.lostAt)}</dd>
              </div>
            ) : null}
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Created</dt>
              <dd className="font-medium text-foreground">
                {opportunity.createdAt ? formatDate(opportunity.createdAt) : "-"}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3">
              <dt className="text-muted-foreground">Updated</dt>
              <dd className="font-medium text-foreground">
                {opportunity.updatedAt ? formatDate(opportunity.updatedAt) : "-"}
              </dd>
            </div>
          </dl>

          {opportunity.lostReason ? (
            <p className="mt-5 rounded-lg border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              Lost because: {opportunity.lostReason}
            </p>
          ) : null}

          {isTerminalStage(opportunity.stage) ? (
            <p className="mt-5 rounded-lg border border-muted bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              This deal is {OPPORTUNITY_STAGE_LABELS[opportunity.stage].toLowerCase()}. Terminal
              stages cannot be changed on this page - use the pipeline board if you need to
              revisit the outcome.
            </p>
          ) : null}
        </section>

        <section className="lg:col-span-2">
          <RelationshipTabs
            entityType="opportunity"
            entityId={opportunityId}
            canWrite={canWrite && !isTerminalStage(opportunity.stage)}
          />
        </section>
      </div>

      <Dialog
        open={pendingStage !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingStage(null);
            setLostReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pendingStage === "won"
                ? "Mark this deal as won?"
                : "Mark this deal as lost?"}
            </DialogTitle>
            <DialogDescription>
              {pendingStage === "won"
                ? "Winning converts this opportunity into a customer and creates a timeline event."
                : "Losing closes the pipeline entry. Add a reason so the team can learn from it."}
            </DialogDescription>
          </DialogHeader>

          {pendingStage === "lost" ? (
            <div className="space-y-1.5">
              <Label htmlFor="lost-reason">Reason (optional)</Label>
              <Textarea
                id="lost-reason"
                value={lostReason}
                onChange={(event) => setLostReason(event.target.value)}
                placeholder="e.g. budget, chose competitor, timing…"
                rows={3}
                maxLength={500}
                disabled={busy}
              />
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setPendingStage(null);
                setLostReason("");
              }}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={pendingStage === "lost" ? "destructive" : "default"}
              onClick={() => void onConfirmStage()}
              disabled={busy}
            >
              {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
