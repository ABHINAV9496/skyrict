"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Columns3, LoaderCircle, TrendingUp } from "lucide-react";

import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
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
import { Textarea } from "@/components/ui/textarea";
import { useModuleAccess } from "@/lib/access/modules";
import {
  changeOpportunityStage,
  listOpportunities,
  type Opportunity,
  type OpportunityStage,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { isTerminalStage, nextStages, PIPELINE_STAGES } from "@/lib/erp/actions";
import { formatDate, formatMoney } from "@/lib/erp/money";
import { opportunityStageBadgeClass, OPPORTUNITY_STAGE_LABELS } from "@/lib/erp/labels";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; opportunities: Opportunity[]; notice?: string };

function opportunityName(opportunity: Opportunity): string {
  return opportunity.name || "Unnamed opportunity";
}

export function OpportunitiesBoard() {
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [pending, setPending] = useState<{ id: string; stage: OpportunityStage } | null>(null);
  const [confirming, setConfirming] = useState<{
    opportunity: Opportunity;
    action: "move" | "won" | "lost";
    stage: OpportunityStage;
  } | null>(null);
  const [lostReason, setLostReason] = useState("");

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listOpportunities({ limit: 100 });
      setStatus({ state: "ready", opportunities: result.data });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load opportunities.";
      setStatus({ state: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const grouped = useMemo(() => {
    if (status.state !== "ready") return new Map<OpportunityStage, Opportunity[]>();
    const map = new Map<OpportunityStage, Opportunity[]>();
    for (const stage of PIPELINE_STAGES) map.set(stage, []);
    for (const opportunity of status.opportunities) {
      map.get(opportunity.stage)?.push(opportunity);
    }
    return map;
  }, [status]);

  async function runMove(opportunity: Opportunity, stage: OpportunityStage) {
    setPending({ id: opportunity.id, stage });
    try {
      await changeOpportunityStage(opportunity.id, stage);
      await load();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not move the opportunity.";
      setStatus((current) =>
        current.state === "ready" ? { ...current, notice: message } : current,
      );
    } finally {
      setPending(null);
    }
  }

  function onConfirm() {
    if (!confirming) return;
    const { opportunity, stage } = confirming;
    setConfirming(null);
    setLostReason("");
    void runMove(opportunity, stage);
  }

  if (status.state === "loading") {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
        {PIPELINE_STAGES.map((stage) => (
          <div key={stage} className="space-y-3">
            <div className="h-8 w-28 rounded-lg bg-muted/70" />
            <div className="h-36 rounded-xl border border-border bg-card" />
            <div className="h-36 rounded-xl border border-border bg-card" />
          </div>
        ))}
      </div>
    );
  }

  if (status.state === "error") {
    return <ErrorState message={status.message} onRetry={() => void load()} />;
  }

  return (
    <div className="space-y-4">
      {status.notice ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
        >
          {status.notice}
        </div>
      ) : null}

      {status.opportunities.length === 0 ? (
        <EmptyState
          icon={TrendingUp}
          title="Your pipeline is empty"
          description="Qualify a lead and it lands here at the prospecting stage, ready to move forward."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-6">
          {PIPELINE_STAGES.map((stage) => {
            const opportunities = grouped.get(stage) ?? [];
            return (
              <section key={stage} aria-label={OPPORTUNITY_STAGE_LABELS[stage]} className="min-w-0">
                <header className="mb-3 flex items-center justify-between gap-2">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Columns3
                      aria-hidden="true"
                      className="size-3.5 text-muted-foreground"
                    />
                    {OPPORTUNITY_STAGE_LABELS[stage]}
                  </h2>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">
                    {opportunities.length}
                  </span>
                </header>
                <div className="space-y-3">
                  {opportunities.map((opportunity) => (
                    <OpportunityCard
                      key={opportunity.id}
                      opportunity={opportunity}
                      canWrite={canWrite}
                      pending={pending}
                      onMove={(nextStage) => setConfirming({ opportunity, action: "move", stage: nextStage })}
                      onWon={() => setConfirming({ opportunity, action: "won", stage: "won" })}
                      onLost={() => {
                        setLostReason("");
                        setConfirming({ opportunity, action: "lost", stage: "lost" });
                      }}
                    />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}

      {/* Confirm dialog for forward moves and the won/lost terminal transitions. */}
      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirming?.action === "lost"
                ? "Mark as lost?"
                : confirming?.action === "won"
                  ? "Mark as won?"
                  : `Move to ${confirming ? OPPORTUNITY_STAGE_LABELS[confirming.stage] : ""}?`}
            </DialogTitle>
            <DialogDescription>
              {confirming?.action === "won"
                ? "The customer will be created from this opportunity in the CRM."
                : confirming?.action === "lost"
                  ? "The pipeline closes and the opportunity can no longer move."
                  : `The opportunity moves forward to the ${confirming ? OPPORTUNITY_STAGE_LABELS[confirming.stage] : ""} stage.`}
            </DialogDescription>
          </DialogHeader>

          {confirming?.action === "lost" ? (
            <div className="space-y-1.5">
              <label htmlFor="lost-reason" className="text-sm font-medium text-foreground">
                Lost reason
              </label>
              <Textarea
                id="lost-reason"
                value={lostReason}
                onChange={(event) => setLostReason(event.target.value)}
                placeholder="e.g. went with a competitor"
                maxLength={500}
                disabled={pending !== null}
              />
            </div>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirming(null)}
              disabled={pending !== null}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={confirming?.action === "lost" ? "destructive" : "default"}
              onClick={onConfirm}
              disabled={pending !== null}
            >
              {pending !== null ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              {confirming?.action === "lost"
                ? "Mark lost"
                : confirming?.action === "won"
                  ? "Mark won"
                  : "Move forward"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function OpportunityCard({
  opportunity,
  canWrite,
  pending,
  onMove,
  onWon,
  onLost,
}: {
  opportunity: Opportunity;
  canWrite: boolean;
  pending: { id: string; stage: OpportunityStage } | null;
  onMove: (stage: OpportunityStage) => void;
  onWon: () => void;
  onLost: () => void;
}) {
  const isBusy = pending?.id === opportunity.id;
  const stages = nextStages(opportunity.stage);
  const terminal = isTerminalStage(opportunity.stage);

  return (
    <article
      className={cn(
        "rounded-xl border border-border bg-card p-3 transition-shadow hover:shadow-sm",
        opportunity.stage === "won" && "border-emerald-500/30",
        opportunity.stage === "lost" && "border-border opacity-80",
      )}
    >
      <div className="min-w-0">
        <h3 className="truncate text-sm font-medium text-foreground">
          {opportunityName(opportunity)}
        </h3>
        <p className="mt-0.5 truncate text-xs text-muted-foreground">
          {opportunity.leadId ? "From qualified lead" : "Manual opportunity"}
        </p>
      </div>

      <div className="mt-3 space-y-1">
        <p className="min-w-0 font-display text-base font-semibold text-foreground tabular-nums">
          {formatMoney(opportunity.amount, opportunity.currency)}
        </p>
        <Badge variant="outline" className={opportunityStageBadgeClass(opportunity.stage)}>
          {OPPORTUNITY_STAGE_LABELS[opportunity.stage]}
        </Badge>
      </div>

      <dl className="mt-3 space-y-1 text-xs text-muted-foreground">
        <div className="flex items-center justify-between gap-2">
          <dt className="min-w-0">Probability</dt>
          <dd className="min-w-0 text-right font-medium text-foreground tabular-nums">
            {opportunity.probability}%
          </dd>
        </div>
        <div className="flex items-center justify-between gap-2">
          <dt className="min-w-0">Expected close</dt>
          <dd className="min-w-0 text-right font-medium text-foreground">
            {formatDate(opportunity.expectedCloseDate)}
          </dd>
        </div>
      </dl>

      {canWrite && !terminal && stages.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1">
          {stages.map((stage) => (
            <Button
              key={stage}
              type="button"
              variant="outline"
              size="xs"
              disabled={pending !== null}
              onClick={() => onMove(stage)}
            >
              {isBusy && pending?.stage === stage ? (
                <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />
              ) : (
                <ArrowRight aria-hidden="true" className="size-3" />
              )}
              {OPPORTUNITY_STAGE_LABELS[stage]}
            </Button>
          ))}
        </div>
      ) : canWrite && opportunity.stage === "negotiation" ? (
        <div className="mt-3 flex flex-wrap gap-1">
          <Button type="button" variant="default" size="xs" disabled={pending !== null} onClick={onWon}>
            {isBusy && pending?.stage === "won" ? (
              <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />
            ) : null}
            Mark won
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="xs"
            disabled={pending !== null}
            onClick={onLost}
          >
            {isBusy && pending?.stage === "lost" ? (
              <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />
            ) : null}
            Mark lost
          </Button>
        </div>
      ) : canWrite && terminal ? (
        <div className="mt-3 h-6" aria-hidden="true" />
      ) : null}
    </article>
  );
}
