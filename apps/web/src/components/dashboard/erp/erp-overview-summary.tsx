"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ShoppingCart, TrendingUp } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { listOpportunities, listOrders } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { formatMoney } from "@/lib/erp/money";

type SummaryStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; pipelineValue: string; openOrders: number; currency: string };

/**
 * Live CRM/Sales summary for the ERP landing page: open pipeline value and
 * the number of open (draft/confirmed) orders.
 */
export function ErpOverviewSummary() {
  const [status, setStatus] = useState<SummaryStatus>({ state: "loading" });

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [opportunitiesResult, ordersResult] = await Promise.all([
        listOpportunities({ limit: 100 }),
        listOrders({ limit: 100 }),
      ]);
      const openOpportunities = opportunitiesResult.data.filter(
        (opportunity) => opportunity.stage !== "won" && opportunity.stage !== "lost",
      );
      const currency =
        openOpportunities.find((opportunity) => opportunity.currency)?.currency ?? "USD";
      const pipelineValue = openOpportunities
        .reduce((sum, opportunity) => sum + (Number(opportunity.amount) || 0), 0)
        .toFixed(2);
      const openOrders = ordersResult.data.filter(
        (order) => order.status === "draft" || order.status === "confirmed",
      ).length;
      setStatus({ state: "ready", pipelineValue, openOrders, currency });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the summary.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="h-28 rounded-xl border border-border bg-card" />
        <div className="h-28 rounded-xl border border-border bg-card" />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-5 py-4">
        <p className="text-sm text-muted-foreground">{status.message}</p>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw aria-hidden="true" className="size-3.5" />
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <Link
        href="/dashboard/erp/crm/opportunities"
        className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-ring/40"
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
            Open pipeline
          </span>
          <TrendingUp
            aria-hidden="true"
            className="size-4 text-primary transition-transform group-hover:-translate-y-0.5"
          />
        </div>
        <p className="mt-3 font-display text-2xl font-semibold text-foreground tabular-nums">
          {formatMoney(status.pipelineValue, status.currency)}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Won and lost opportunities excluded
        </p>
      </Link>

      <Link
        href="/dashboard/erp/orders"
        className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-ring/40"
      >
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
            Open orders
          </span>
          <ShoppingCart
            aria-hidden="true"
            className="size-4 text-primary transition-transform group-hover:-translate-y-0.5"
          />
        </div>
        <p className="mt-3 font-display text-2xl font-semibold text-foreground tabular-nums">
          {status.openOrders}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Draft and confirmed orders awaiting fulfilment
        </p>
      </Link>
    </div>
  );
}
