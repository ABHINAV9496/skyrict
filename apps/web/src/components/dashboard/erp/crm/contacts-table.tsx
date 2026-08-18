"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ContactRound, LoaderCircle, Pencil, Plus, Search, UserX } from "lucide-react";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { Pagination, offsetMeta } from "@/components/dashboard/erp/pagination";
import { ContactFormDialog } from "@/components/dashboard/erp/crm/contact-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import {
  deactivateContact,
  listContacts,
  listCustomers,
  type Contact,
  type Customer,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; contacts: Contact[]; total: number; notice?: string };

function contactName(contact: Contact): string {
  const name = [contact.firstName, contact.lastName].filter(Boolean).join(" ");
  return name || "Unnamed contact";
}

export function ContactsTable() {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerFilter, setCustomerFilter] = useState<string>("all");
  const [includeInactive, setIncludeInactive] = useState(false);
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Contact | null>(null);
  const [deactivating, setDeactivating] = useState<Contact | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [contactsResult, customersResult] = await Promise.all([
        listContacts({
          customerId: customerFilter === "all" ? undefined : customerFilter,
          includeInactive,
          offset,
          limit: PAGE_SIZE,
        }),
        listCustomers({ limit: 100 }),
      ]);
      setCustomers(customersResult.data);
      setStatus({
        state: "ready",
        contacts: contactsResult.data,
        total: contactsResult.meta.total,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load contacts.";
      setStatus({ state: "error", message });
    }
  }, [customerFilter, includeInactive, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const customerName = useMemo(() => {
    const map = new Map(customers.map((customer) => [customer.id, customer.name]));
    return (customerId: string) => map.get(customerId) ?? null;
  }, [customers]);

  const visibleContacts = useMemo(() => {
    if (status.state !== "ready") return [];
    const term = query.trim().toLowerCase();
    if (!term) return status.contacts;
    return status.contacts.filter((contact) =>
      [
        contact.firstName,
        contact.lastName,
        contact.email,
        contact.phone,
        contact.jobTitle,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term)),
    );
  }, [status, query]);

  async function onDeactivate() {
    if (!deactivating) return;
    setBusy(true);
    try {
      await deactivateContact(deactivating.id);
      await load();
      setDeactivating(null);
    } catch (error) {
      setStatus((current) => ({
        ...current,
        notice:
          error instanceof ApiError ? error.message : "Could not deactivate the contact.",
      }));
    } finally {
      setBusy(false);
    }
  }

  const columns: ErpColumn<Contact>[] = [
    {
      key: "name",
      label: "Contact",
      render: (contact) => (
        <div className="min-w-0">
          <p className="truncate font-medium text-foreground">{contactName(contact)}</p>
          {contact.jobTitle ? (
            <p className="truncate text-xs text-muted-foreground">{contact.jobTitle}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "customer",
      label: "Customer",
      render: (contact) => {
        const name = customerName(contact.customerId);
        return (
          <span className="text-foreground">{name ?? contact.customerId.slice(0, 8)}</span>
        );
      },
    },
    {
      key: "contact",
      label: "Contact info",
      render: (contact) => (
        <div className="min-w-0">
          <p className="truncate text-foreground">{contact.email || "—"}</p>
          <p className="truncate text-xs text-muted-foreground">{contact.phone || ""}</p>
        </div>
      ),
    },
    {
      key: "primary",
      label: "Role",
      render: (contact) =>
        contact.isPrimary ? (
          <Badge
            variant="outline"
            className="bg-primary/10 text-primary ring-1 ring-primary/30"
          >
            Primary
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "status",
      label: "Status",
      render: (contact) => (
        <Badge
          variant="outline"
          className={cn(
            contact.isActive
              ? "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400"
              : "bg-muted text-muted-foreground ring-1 ring-border",
          )}
        >
          {contact.isActive ? "Active" : "Inactive"}
        </Badge>
      ),
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      className: "w-24",
      render: (contact) =>
        canWrite ? (
          <div className="flex items-center justify-end gap-1">
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`Edit ${contactName(contact)}`}
              title="Edit contact"
              onClick={(event) => {
                event.stopPropagation();
                setEditing(contact);
              }}
            >
              <Pencil aria-hidden="true" className="size-3.5 text-muted-foreground" />
            </Button>
            {contact.isActive ? (
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={`Deactivate ${contactName(contact)}`}
                title="Deactivate"
                onClick={(event) => {
                  event.stopPropagation();
                  setDeactivating(contact);
                }}
              >
                <UserX aria-hidden="true" className="size-3.5 text-muted-foreground" />
              </Button>
            ) : null}
          </div>
        ) : null,
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="h-8 w-44 rounded-lg bg-muted/70" />
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
        <ErrorState message={status.message} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={customerFilter}
            onValueChange={(value) => {
              setCustomerFilter(value);
              setOffset(0);
            }}
          >
            <SelectTrigger className="w-48" aria-label="Filter by customer">
              <SelectValue placeholder="All customers" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All customers</SelectItem>
              {customers.map((customer) => (
                <SelectItem key={customer.id} value={customer.id}>
                  {customer.name}
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
              placeholder="Search name, email, phone"
              aria-label="Search contacts"
            />
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
            <Checkbox
              checked={includeInactive}
              onCheckedChange={(checked) => {
                setIncludeInactive(checked === true);
                setOffset(0);
              }}
            />
            Show inactive
          </label>
        </div>
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" className="size-4" />
            New contact
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

      {visibleContacts.length === 0 ? (
        <EmptyState
          icon={ContactRound}
          title={
            query.trim() || customerFilter !== "all"
              ? "No matching contacts"
              : "No contacts yet"
          }
          description={
            query.trim() || customerFilter !== "all"
              ? "Try a different search or filter."
              : "Contacts are people on a customer account — they also show up in the customer timeline."
          }
          action={
            canWrite && !query.trim() && customerFilter === "all" ? (
              <Button type="button" variant="outline" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden="true" className="size-4" />
                New contact
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ErpTable
          columns={columns}
          rows={visibleContacts}
          rowKey={(contact) => contact.id}
          onRowClick={(contact) =>
            router.push(`/dashboard/erp/crm/customers/${contact.customerId}`)
          }
          footer={
            <Pagination
              meta={offsetMeta(offset, PAGE_SIZE, status.total)}
              onPageChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
            />
          }
        />
      )}

      <ContactFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        customers={customers}
        onSaved={() => {
          setOffset(0);
          void load();
        }}
      />

      <ContactFormDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        customers={customers}
        contact={editing}
        onSaved={() => void load()}
      />

      <Dialog open={deactivating !== null} onOpenChange={(open) => !open && setDeactivating(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Deactivate {deactivating ? contactName(deactivating) : "contact"}?</DialogTitle>
            <DialogDescription>
              The contact can no longer be selected and drops out of the active contacts list.
              Timeline history stays intact.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeactivating(null)}
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
