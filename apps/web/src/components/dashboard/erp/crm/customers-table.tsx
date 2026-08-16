"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search, Users } from "lucide-react";
import { useRouter } from "next/navigation";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { Pagination } from "@/components/dashboard/erp/pagination";
import { CustomerFormDialog } from "@/components/dashboard/erp/crm/customer-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { useModuleAccess } from "@/lib/access/modules";
import { listCustomers, type Customer } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/erp/money";

const PAGE_SIZE = 50;

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; customers: Customer[]; total: number };

export function CustomersTable() {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [includeInactive, setIncludeInactive] = useState(false);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listCustomers({
        includeInactive,
        offset,
        limit: PAGE_SIZE,
      });
      setStatus({ state: "ready", customers: result.data, total: result.meta.total });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load customers.";
      setStatus({ state: "error", message });
    }
  }, [includeInactive, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleCustomers = useMemo(() => {
    if (status.state !== "ready") return [];
    const term = query.trim().toLowerCase();
    if (!term) return status.customers;
    return status.customers.filter((customer) =>
      [customer.name, customer.customerCode, customer.email, customer.phone]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term)),
    );
  }, [status, query]);

  const columns: ErpColumn<Customer>[] = [
    {
      key: "name",
      label: "Customer",
      render: (customer) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground">{customer.name}</p>
          <p className="truncate text-xs text-muted-foreground">{customer.customerCode}</p>
        </div>
      ),
    },
    {
      key: "contact",
      label: "Contact",
      render: (customer) => (
        <div className="min-w-0">
          <p className="truncate text-foreground">{customer.email || "—"}</p>
          <p className="truncate text-xs text-muted-foreground">{customer.phone || ""}</p>
        </div>
      ),
    },
    {
      key: "creditLimit",
      label: "Credit limit",
      align: "right",
      render: (customer) => (
        <span className="font-medium text-foreground tabular-nums">
          {formatMoney(customer.creditLimit, customer.currency)}
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (customer) => (
        <Badge
          variant="outline"
          className={
            customer.isActive
              ? "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400"
              : "bg-muted text-muted-foreground ring-1 ring-border"
          }
        >
          {customer.isActive ? "Active" : "Inactive"}
        </Badge>
      ),
    },
    {
      key: "created",
      label: "Customer since",
      render: (customer) => (
        <span className="text-foreground">{formatDate(customer.createdAt)}</span>
      ),
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="h-8 w-56 rounded-lg bg-muted/70" />
          <div className="h-8 w-28 rounded-lg bg-muted/70" />
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
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search
              aria-hidden="true"
              className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="w-56 pl-8"
              placeholder="Search name, code, email"
              aria-label="Search customers"
            />
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <Checkbox
              checked={includeInactive}
              onCheckedChange={(checked) => {
                setIncludeInactive(Boolean(checked));
                setOffset(0);
              }}
            />
            Show inactive
          </label>
        </div>
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" className="size-4" />
            New customer
          </Button>
        ) : null}
      </div>

      {visibleCustomers.length === 0 ? (
        <EmptyState
          icon={Users}
          title={query.trim() || includeInactive ? "No matching customers" : "No customers yet"}
          description={
            query.trim() || includeInactive
              ? "Try a different search or uncheck the filters."
              : "Customers appear automatically from won opportunities, or you can add one now."
          }
          action={
            canWrite && !query.trim() && !includeInactive ? (
              <Button type="button" variant="outline" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden="true" className="size-4" />
                New customer
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ErpTable
          columns={columns}
          rows={visibleCustomers}
          rowKey={(customer) => customer.id}
          onRowClick={(customer) =>
            router.push(`/dashboard/erp/crm/customers/${customer.id}`)
          }
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

      <CustomerFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSaved={() => {
          setOffset(0);
          void load();
        }}
      />
    </div>
  );
}
