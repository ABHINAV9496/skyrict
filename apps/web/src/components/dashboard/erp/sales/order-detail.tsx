"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  LoaderCircle,
  PackageCheck,
  ShoppingCart,
  XCircle,
} from "lucide-react";
import Link from "next/link";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
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
import { Skeleton } from "@/components/ui/skeleton";
import { useModuleAccess } from "@/lib/access/modules";
import {
  cancelOrder,
  confirmOrder,
  fulfilOrder,
  getOrder,
  listOrderLines,
  type OrderLine,
  type SalesOrder,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { orderActions } from "@/lib/erp/actions";
import { formatDate, formatMoney, formatNumber } from "@/lib/erp/money";
import { orderStatusBadgeClass, ORDER_STATUS_LABELS } from "@/lib/erp/labels";
import { setPageTitle } from "@/lib/topbar-title";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; order: SalesOrder; lines: OrderLine[]; notice?: string };

type PendingAction = "confirm" | "fulfil" | "cancel" | null;

interface OrderDetailProps {
  orderId: string;
}

export function OrderDetail({ orderId }: OrderDetailProps) {
  const { permissions } = useModuleAccess();
  const canApprove = permissions.includes("*") || permissions.includes("erp.sales.approve");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [pendingAction, setPendingAction] = useState<PendingAction>(null);
  const [confirmAction, setConfirmAction] = useState<PendingAction>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [order, lines] = await Promise.all([getOrder(orderId), listOrderLines(orderId)]);
      setStatus({ state: "ready", order, lines });
      setPageTitle(order.orderNumber);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not load the order.";
      setStatus({ state: "error", message });
      setPageTitle(null);
    }
  }, [orderId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => setPageTitle(null), []);

  async function runAction(action: Exclude<PendingAction, null>) {
    if (status.state !== "ready") return;
    const order = status.order;
    setPendingAction(action);
    setConfirmAction(null);
    try {
      if (action === "confirm") await confirmOrder(order.id);
      if (action === "fulfil") await fulfilOrder(order.id);
      if (action === "cancel") await cancelOrder(order.id);
      await load();
    } catch (error) {
      setStatus((current) =>
        current.state === "ready"
          ? {
              ...current,
              notice:
                error instanceof ApiError
                  ? error.message
                  : "The action could not be completed.",
            }
          : current,
      );
    } finally {
      setPendingAction(null);
    }
  }

  const confirmDialogCopy: Record<
    Exclude<PendingAction, null>,
    { title: string; description: string; button: string }
  > = {
    confirm: {
      title: "Confirm this order?",
      description:
        "Confirmation runs the credit check and locks the order for fulfilment. This cannot be undone.",
      button: "Confirm order",
    },
    fulfil: {
      title: "Fulfil this order?",
      description:
        "The order will be marked fulfilled. This cannot be undone.",
      button: "Fulfil order",
    },
    cancel: {
      title: "Cancel this order?",
      description:
        "The order will be cancelled and can no longer be confirmed or fulfilled.",
      button: "Cancel order",
    },
  };

  const columns: ErpColumn<OrderLine>[] = [
    {
      key: "product",
      label: "Product",
      render: (line) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground">{line.productName || "—"}</p>
          <p className="truncate text-xs text-muted-foreground">{line.sku}</p>
        </div>
      ),
    },
    {
      key: "quantity",
      label: "Qty",
      align: "right",
      render: (line) => (
        <span className="text-foreground tabular-nums">{formatNumber(line.quantity)}</span>
      ),
    },
    {
      key: "unitPrice",
      label: "Unit price",
      align: "right",
      render: (line) => (
        <span className="text-foreground tabular-nums">
          {formatMoney(line.unitPrice, status.state === "ready" ? status.order.currency : undefined)}
        </span>
      ),
    },
    {
      key: "lineTotal",
      label: "Line total",
      align: "right",
      render: (line) => (
        <span className="font-medium text-foreground tabular-nums">
          {formatMoney(line.lineTotal, status.state === "ready" ? status.order.currency : undefined)}
        </span>
      ),
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 rounded-lg bg-muted/70" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-48 rounded-xl" />
          <Skeleton className="h-72 rounded-xl lg:col-span-2" />
        </div>
      </div>
    );
  }

  if (status.state === "error") {
    return <ErrorState message={status.message} onRetry={() => void load()} />;
  }

  const { order, lines } = status;
  const actions = orderActions(order.status);
  const terminal = order.status === "fulfilled" || order.status === "cancelled";
  const hasActions = canApprove && !terminal && (actions.confirm || actions.fulfil || actions.cancel);

  return (
    <div className="space-y-4">
      <div>
        <Button type="button" variant="ghost" size="sm" asChild>
          <Link href="/dashboard/erp/orders">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to orders
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
              <ShoppingCart aria-hidden="true" className="size-5" />
            </div>
            <Badge variant="outline" className={orderStatusBadgeClass(order.status)}>
              {ORDER_STATUS_LABELS[order.status]}
            </Badge>
          </div>

          <h2 className="mt-4 font-display text-lg font-semibold text-foreground">
            {order.orderNumber}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">Sales order</p>

          <dl className="mt-5 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-muted-foreground">Credit check</dt>
              <dd>
                <Badge
                  variant="outline"
                  className={cn(
                    order.creditCheck === "passed" &&
                      "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
                    order.creditCheck === "failed" &&
                      "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
                    order.creditCheck === "pending" &&
                      "bg-muted text-muted-foreground ring-1 ring-border",
                  )}
                >
                  {order.creditCheck}
                </Badge>
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-muted-foreground">Created</dt>
              <dd className="text-foreground">{formatDate(order.createdAt)}</dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-muted-foreground">Confirmed</dt>
              <dd className="text-foreground">{formatDate(order.confirmedAt)}</dd>
            </div>
          </dl>

          <dl className="mt-5 space-y-1.5 border-t border-border pt-4 text-sm">
            <div className="flex items-center justify-between">
              <dt className="text-muted-foreground">Subtotal</dt>
              <dd className="text-foreground tabular-nums">
                {formatMoney(order.subtotal, order.currency)}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-muted-foreground">Discount</dt>
              <dd className="text-foreground tabular-nums">
                {formatMoney(order.discount, order.currency)}
              </dd>
            </div>
            <div className="flex items-center justify-between">
              <dt className="text-muted-foreground">Tax</dt>
              <dd className="text-foreground tabular-nums">
                {formatMoney(order.tax, order.currency)}
              </dd>
            </div>
            <div className="flex items-center justify-between border-t border-border pt-2">
              <dt className="font-semibold text-foreground">Total</dt>
              <dd className="font-display text-lg font-semibold text-foreground tabular-nums">
                {formatMoney(order.total, order.currency)}
              </dd>
            </div>
          </dl>
        </section>

        <section className="space-y-4 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-display text-base font-semibold text-foreground">Line items</h2>
            {hasActions ? (
              <div className="flex flex-wrap gap-1.5">
                {actions.confirm ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={pendingAction !== null}
                    onClick={() => setConfirmAction("confirm")}
                  >
                    {pendingAction === "confirm" ? (
                      <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      <CheckCircle2 aria-hidden="true" className="size-4" />
                    )}
                    Confirm
                  </Button>
                ) : null}
                {actions.fulfil ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={pendingAction !== null}
                    onClick={() => setConfirmAction("fulfil")}
                  >
                    {pendingAction === "fulfil" ? (
                      <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      <PackageCheck aria-hidden="true" className="size-4" />
                    )}
                    Fulfil
                  </Button>
                ) : null}
                {actions.cancel ? (
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    disabled={pendingAction !== null}
                    onClick={() => setConfirmAction("cancel")}
                  >
                    {pendingAction === "cancel" ? (
                      <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                    ) : (
                      <XCircle aria-hidden="true" className="size-4" />
                    )}
                    Cancel
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>

          <ErpTable
            columns={columns}
            rows={lines}
            rowKey={(line) => line.id}
            emptyMessage="This order has no line items."
          />
        </section>
      </div>

      <Dialog
        open={confirmAction !== null}
        onOpenChange={(open) => !open && setConfirmAction(null)}
      >
        <DialogContent>
          {confirmAction ? (
            <>
              <DialogHeader>
                <DialogTitle>{confirmDialogCopy[confirmAction].title}</DialogTitle>
                <DialogDescription>
                  {confirmDialogCopy[confirmAction].description}
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setConfirmAction(null)}
                  disabled={pendingAction !== null}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant={confirmAction === "cancel" ? "destructive" : "default"}
                  onClick={() => void runAction(confirmAction)}
                  disabled={pendingAction !== null}
                >
                  {pendingAction !== null ? (
                    <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                  ) : null}
                  {confirmDialogCopy[confirmAction].button}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
