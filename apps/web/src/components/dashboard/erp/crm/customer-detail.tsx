"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Building2,
  LoaderCircle,
  Mail,
  Pencil,
  Phone,
  Plus,
  ShoppingCart,
  UserX,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { CustomerFormDialog } from "@/components/dashboard/erp/crm/customer-form-dialog";
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
  deactivateCustomer,
  getCustomer,
  listOrders,
  type Customer,
  type SalesOrder,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/erp/money";
import { orderStatusBadgeClass, ORDER_STATUS_LABELS } from "@/lib/erp/labels";
import { setPageTitle } from "@/lib/topbar-title";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; customer: Customer; orders: SalesOrder[]; notice?: string };

interface CustomerDetailProps {
  customerId: string;
}

export function CustomerDetail({ customerId }: CustomerDetailProps) {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [editOpen, setEditOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [customer, ordersResult] = await Promise.all([
        getCustomer(customerId),
        listOrders({ customerId, limit: 100 }),
      ]);
      setStatus({ state: "ready", customer, orders: ordersResult.data });
      setPageTitle(customer.name);
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load the customer.";
      setStatus({ state: "error", message });
      setPageTitle(null);
    }
  }, [customerId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => () => setPageTitle(null), []);

  async function onDeactivate() {
    setBusy(true);
    try {
      await deactivateCustomer(customerId);
      await load();
      setDeactivateOpen(false);
    } catch (error) {
      setStatus((current) => ({
        ...current,
        notice:
          error instanceof ApiError ? error.message : "Could not deactivate the customer.",
      }));
    } finally {
      setBusy(false);
    }
  }

  const columns: ErpColumn<SalesOrder>[] = [
    {
      key: "orderNumber",
      label: "Order",
      render: (order) => (
        <span className="font-medium text-foreground">{order.orderNumber}</span>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (order) => (
        <Badge variant="outline" className={orderStatusBadgeClass(order.status)}>
          {ORDER_STATUS_LABELS[order.status]}
        </Badge>
      ),
    },
    {
      key: "creditCheck",
      label: "Credit check",
      render: (order) => (
        <Badge variant="outline" className={cn("bg-muted text-muted-foreground ring-1 ring-border")}>
          {order.creditCheck}
        </Badge>
      ),
    },
    {
      key: "created",
      label: "Created",
      render: (order) => <span className="text-foreground">{formatDate(order.createdAt)}</span>,
    },
    {
      key: "total",
      label: "Total",
      align: "right",
      render: (order) => (
        <span className="font-medium text-foreground tabular-nums">
          {formatMoney(order.total, order.currency)}
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
          <Skeleton className="h-48 rounded-xl lg:col-span-2" />
        </div>
      </div>
    );
  }

  if (status.state === "error") {
    return <ErrorState message={status.message} onRetry={() => void load()} />;
  }

  const { customer, orders } = status;

  return (
    <div className="space-y-4">
      <div>
        <Button type="button" variant="ghost" size="sm" asChild>
          <Link href="/dashboard/erp/crm/customers">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to customers
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
              <Building2 aria-hidden="true" className="size-5" />
            </div>
            {canWrite ? (
              <div className="flex gap-1">
                <Button
                  type="button"
                  variant="outline"
                  size="icon-xs"
                  aria-label="Edit customer"
                  onClick={() => setEditOpen(true)}
                >
                  <Pencil aria-hidden="true" className="size-3.5" />
                </Button>
                {customer.isActive ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Deactivate customer"
                    onClick={() => setDeactivateOpen(true)}
                  >
                    <UserX aria-hidden="true" className="size-3.5 text-muted-foreground" />
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>

          <h2 className="mt-4 font-display text-lg font-semibold text-foreground">
            {customer.name}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">{customer.customerCode}</p>

          <dl className="mt-5 space-y-3 text-sm">
            <div className="flex items-center gap-2 text-muted-foreground">
              <Mail aria-hidden="true" className="size-4 shrink-0" />
              <span className="min-w-0 truncate">{customer.email || "No email on file"}</span>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <Phone aria-hidden="true" className="size-4 shrink-0" />
              <span>{customer.phone || "No phone on file"}</span>
            </div>
          </dl>

          <dl className="mt-5 grid grid-cols-2 gap-3 border-t border-border pt-4">
            <div>
              <dt className="text-xs text-muted-foreground">Credit limit</dt>
              <dd className="mt-1 font-display text-base font-semibold text-foreground tabular-nums">
                {formatMoney(customer.creditLimit, customer.currency)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Customer since</dt>
              <dd className="mt-1 font-display text-base font-semibold text-foreground">
                {formatDate(customer.createdAt)}
              </dd>
            </div>
          </dl>

          <Badge
            variant="outline"
            className={cn(
              "mt-4",
              customer.isActive
                ? "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400"
                : "bg-muted text-muted-foreground ring-1 ring-border",
            )}
          >
            {customer.isActive ? "Active" : "Inactive"}
          </Badge>
        </section>

        <section className="space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
              <ShoppingCart aria-hidden="true" className="size-4 text-primary" />
              Order history
            </h2>
            {canWrite && customer.isActive ? (
              <Button type="button" size="sm" onClick={() => router.push("/dashboard/erp/orders")}>
                <Plus aria-hidden="true" className="size-4" />
                New order
              </Button>
            ) : null}
          </div>

          {orders.length === 0 ? (
            <EmptyState
              icon={ShoppingCart}
              title="No orders yet"
              description="Orders created for this customer will appear here."
            />
          ) : (
            <ErpTable
              columns={columns}
              rows={orders}
              rowKey={(order) => order.id}
              onRowClick={(order) => router.push(`/dashboard/erp/orders/${order.id}`)}
            />
          )}
        </section>
      </div>

      <CustomerFormDialog
        open={editOpen}
        onOpenChange={setEditOpen}
        customer={customer}
        onSaved={async () => {
          await load();
        }}
      />

      <Dialog open={deactivateOpen} onOpenChange={setDeactivateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deactivate {customer.name}?</DialogTitle>
            <DialogDescription>
              The customer can no longer place new orders and disappears from the active list.
              History stays intact — you can reactivate through the API later.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeactivateOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={onDeactivate} disabled={busy}>
              {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Deactivate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
