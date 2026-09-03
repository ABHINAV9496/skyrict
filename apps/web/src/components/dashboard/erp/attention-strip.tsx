"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowUpRight, CheckCircle2, Clock, PackageX, Receipt, RefreshCw, ShoppingBag } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { listOpportunities, listOrders } from "@/lib/api/crm-api";
import { listInvoices } from "@/lib/api/finance-api";
import { listProducts } from "@/lib/api/inventory-api";

interface AttentionState {
  state: "loading" | "error" | "ready";
  outOfStock: number;
  overdueInvoices: number;
  stalledOpportunities: number;
  openOrders: number;
  errorMessage?: string;
}

/**
 * Compact high-priority exceptions strip for decision items needing immediate attention.
 * Replaces the wall-of-text executive summary as the top hero widget on the ERP home.
 */
export function AttentionStrip() {
  const [data, setData] = useState<AttentionState>({
    state: "loading",
    outOfStock: 0,
    overdueInvoices: 0,
    stalledOpportunities: 0,
    openOrders: 0,
  });

  const load = useCallback(async () => {
    setData((prev) => ({ ...prev, state: "loading" }));
    try {
      const [productsRes, invoicesRes, opportunitiesRes, ordersRes] = await Promise.allSettled([
        listProducts({ pageSize: 100 }),
        listInvoices(),
        listOpportunities({ limit: 100 }),
        listOrders({ limit: 100 }),
      ]);

      let outOfStock = 0;
      if (productsRes.status === "fulfilled" && productsRes.value?.data) {
        outOfStock = productsRes.value.data.filter(
          (p) => !p.isActive || (p.reorderPoint != null && Number(p.reorderPoint) <= 0),
        ).length;
      }

      let overdueInvoices = 0;
      if (invoicesRes.status === "fulfilled" && invoicesRes.value?.data) {
        const now = new Date().toISOString().split("T")[0];
        overdueInvoices = invoicesRes.value.data.filter(
          (inv) => (inv.status === "issued" || inv.status === "approved") && inv.due_date && inv.due_date < now,
        ).length;
      }

      let stalledOpportunities = 0;
      if (opportunitiesRes.status === "fulfilled" && opportunitiesRes.value?.data) {
        stalledOpportunities = opportunitiesRes.value.data.filter(
          (opp) => opp.stage !== "won" && opp.stage !== "lost",
        ).length;
      }

      let openOrders = 0;
      if (ordersRes.status === "fulfilled" && ordersRes.value?.data) {
        openOrders = ordersRes.value.data.filter(
          (ord) => ord.status === "draft" || ord.status === "confirmed",
        ).length;
      }

      setData({
        state: "ready",
        outOfStock,
        overdueInvoices,
        stalledOpportunities,
        openOrders,
      });
    } catch {
      setData({
        state: "error",
        outOfStock: 0,
        overdueInvoices: 0,
        stalledOpportunities: 0,
        openOrders: 0,
        errorMessage: "Unable to load attention items.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (data.state === "loading") {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-card p-4" />
        ))}
      </div>
    );
  }

  if (data.state === "error") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-5 py-4">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <AlertTriangle className="size-4 text-amber-500" />
          <span>{data.errorMessage}</span>
        </div>
        <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="mr-1.5 size-3.5" />
          Retry
        </Button>
      </div>
    );
  }

  const items = [
    {
      label: "Out of Stock SKUs",
      count: data.outOfStock,
      href: "/dashboard/erp/inventory",
      icon: PackageX,
      tone: data.outOfStock > 0 ? "border-amber-500/30 bg-amber-500/5 text-amber-500" : "border-border text-muted-foreground",
      description: data.outOfStock > 0 ? "Items at or below reorder threshold" : "All stock levels healthy",
    },
    {
      label: "Overdue Invoices",
      count: data.overdueInvoices,
      href: "/dashboard/erp/finance",
      icon: Receipt,
      tone: data.overdueInvoices > 0 ? "border-red-500/30 bg-red-500/5 text-red-500" : "border-border text-muted-foreground",
      description: data.overdueInvoices > 0 ? "Invoices past payment terms" : "No overdue receivables",
    },
    {
      label: "Open Opportunities",
      count: data.stalledOpportunities,
      href: "/dashboard/erp/crm/opportunities",
      icon: Clock,
      tone: data.stalledOpportunities > 0 ? "border-primary/30 bg-primary/5 text-primary" : "border-border text-muted-foreground",
      description: data.stalledOpportunities > 0 ? "Active pipeline deals in progress" : "No active pipeline deals",
    },
    {
      label: "Open Sales Orders",
      count: data.openOrders,
      href: "/dashboard/erp/orders",
      icon: ShoppingBag,
      tone: data.openOrders > 0 ? "border-primary/30 bg-primary/5 text-primary" : "border-border text-muted-foreground",
      description: data.openOrders > 0 ? "Orders awaiting fulfilment" : "All orders fulfilled",
    },
  ];

  const totalUrgent = data.outOfStock + data.overdueInvoices;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="font-display text-sm font-semibold tracking-wider text-muted-foreground uppercase">
            Attention Needed
          </h2>
          {totalUrgent > 0 ? (
            <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-500">
              {totalUrgent} urgent
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-500">
              <CheckCircle2 className="size-3" />
              All clear
            </span>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            className="group flex flex-col justify-between rounded-xl border border-border bg-card p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-muted/30"
          >
            <div>
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                <div className={`flex size-7 items-center justify-center rounded-md border ${item.tone}`}>
                  <item.icon className="size-3.5" />
                </div>
              </div>
              <p className="mt-2 font-display text-2xl font-semibold tracking-tight text-foreground tabular-nums">
                {item.count}
              </p>
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-border/50 pt-2">
              <span className="text-xs text-muted-foreground">{item.description}</span>
              <ArrowUpRight className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary" />
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
