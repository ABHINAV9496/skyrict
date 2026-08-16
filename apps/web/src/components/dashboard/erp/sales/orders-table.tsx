"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search, ShoppingCart } from "lucide-react";
import { useRouter } from "next/navigation";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { Pagination } from "@/components/dashboard/erp/pagination";
import { OrderCreateDialog } from "@/components/dashboard/erp/sales/order-create-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { useModuleAccess } from "@/lib/access/modules";
import { listOrders, type OrderStatus, type SalesOrder } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/erp/money";
import { orderStatusBadgeClass, ORDER_STATUS_LABELS } from "@/lib/erp/labels";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const STATUS_FILTERS: { value: OrderStatus | "all"; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "draft", label: "Draft" },
  { value: "confirmed", label: "Confirmed" },
  { value: "fulfilled", label: "Fulfilled" },
  { value: "cancelled", label: "Cancelled" },
];

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; orders: SalesOrder[]; total: number };

export function OrdersTable() {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.sales.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [statusFilter, setStatusFilter] = useState<OrderStatus | "all">("all");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listOrders({
        status: statusFilter === "all" ? undefined : statusFilter,
        offset,
        limit: PAGE_SIZE,
      });
      setStatus({ state: "ready", orders: result.data, total: result.meta.total });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Could not load orders.";
      setStatus({ state: "error", message });
    }
  }, [statusFilter, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleOrders = useMemo(() => {
    if (status.state !== "ready") return [];
    const term = query.trim().toLowerCase();
    if (!term) return status.orders;
    return status.orders.filter((order) =>
      order.orderNumber.toLowerCase().includes(term),
    );
  }, [status, query]);

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
        <Badge
          variant="outline"
          className={cn(
            order.creditCheck === "passed" &&
              "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
            order.creditCheck === "failed" &&
              "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
            order.creditCheck === "pending" && "bg-muted text-muted-foreground ring-1 ring-border",
          )}
        >
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
      key: "confirmed",
      label: "Confirmed",
      render: (order) => (
        <span className="text-foreground">{formatDate(order.confirmedAt)}</span>
      ),
    },
    {
      key: "total",
      label: "Total",
      align: "right",
      render: (order) => (
        <span className="font-display font-semibold text-foreground tabular-nums">
          {formatMoney(order.total, order.currency)}
        </span>
      ),
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
    return <ErrorState message={status.message} onRetry={() => void load()} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={statusFilter}
            onValueChange={(value) => {
              setStatusFilter(value as OrderStatus | "all");
              setOffset(0);
            }}
          >
            <SelectTrigger className="w-40" aria-label="Filter by status">
              <SelectValue placeholder="All statuses" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((filter) => (
                <SelectItem key={filter.value} value={filter.value}>
                  {filter.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="relative">
            <Search
              aria-hidden="true"
              className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-56 pl-8"
              placeholder="Search order number"
              aria-label="Search orders"
            />
          </div>
        </div>
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" className="size-4" />
            New order
          </Button>
        ) : null}
      </div>

      {visibleOrders.length === 0 ? (
        <EmptyState
          icon={ShoppingCart}
          title={query.trim() || statusFilter !== "all" ? "No matching orders" : "No orders yet"}
          description={
            query.trim() || statusFilter !== "all"
              ? "Try a different search or filter."
              : "Create an order for a customer to get the sales flow moving."
          }
          action={
            canWrite && !query.trim() && statusFilter === "all" ? (
              <Button type="button" variant="outline" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden="true" className="size-4" />
                New order
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ErpTable
          columns={columns}
          rows={visibleOrders}
          rowKey={(order) => order.id}
          onRowClick={(order) => router.push(`/dashboard/erp/orders/${order.id}`)}
          footer={
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={status.total}
              onPageChange={setOffset}
            />
          }
        />
      )}

      <OrderCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(order) => {
          setOffset(0);
          router.push(`/dashboard/erp/orders/${order.id}`);
        }}
      />
    </div>
  );
}
