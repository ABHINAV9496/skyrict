"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ArrowLeft,
  Building2,
  ClipboardList,
  ContactRound,
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
import { NotesCard, TimelineCard } from "@/components/dashboard/erp/crm/anchor-panels";
import { ContactFormDialog } from "@/components/dashboard/erp/crm/contact-form-dialog";
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
  deactivateContact,
  deactivateCustomer,
  getCustomer,
  listContacts,
  listOrders,
  type Contact,
  type Customer,
  type SalesOrder,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { orderStatusBadgeClass, ORDER_STATUS_LABELS } from "@/lib/erp/labels";
import { formatDate, formatMoney } from "@/lib/erp/money";
import { setPageTitle } from "@/lib/topbar-title";
import { cn } from "@/lib/utils";

type Tab = "orders" | "contacts" | "notes" | "timeline";

const TABS: { key: Tab; label: string; icon: typeof ClipboardList }[] = [
  { key: "orders", label: "Orders", icon: ShoppingCart },
  { key: "contacts", label: "Contacts", icon: ContactRound },
  { key: "notes", label: "Notes", icon: ClipboardList },
  { key: "timeline", label: "Timeline", icon: ClipboardList },
];

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      customer: Customer;
      orders: SalesOrder[];
      contacts: Contact[];
      notice?: string;
    };

interface CustomerDetailProps {
  customerId: string;
}

function contactName(contact: Contact): string {
  const name = [contact.firstName, contact.lastName].filter(Boolean).join(" ");
  return name || "Unnamed contact";
}

export function CustomerDetail({ customerId }: CustomerDetailProps) {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [tab, setTab] = useState<Tab>("orders");
  const [editOpen, setEditOpen] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);
  const [addContactOpen, setAddContactOpen] = useState(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);
  const [deactivatingContact, setDeactivatingContact] = useState<Contact | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [customer, ordersResult, contactsResult] = await Promise.all([
        getCustomer(customerId),
        listOrders({ customerId, limit: 100 }),
        listContacts({ customerId, limit: 100 }),
      ]);
      setStatus({
        state: "ready",
        customer,
        orders: ordersResult.data,
        contacts: contactsResult.data,
      });
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

  async function onDeactivateContact() {
    if (!deactivatingContact) return;
    setBusy(true);
    try {
      await deactivateContact(deactivatingContact.id);
      await load();
      setDeactivatingContact(null);
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

  const orderColumns: ErpColumn<SalesOrder>[] = [
    {
      key: "orderNumber",
      label: "Order",
      render: (order) => <span className="font-medium text-foreground">{order.orderNumber}</span>,
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

  const { customer, orders, contacts } = status;

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
          <nav
            aria-label="Customer record sections"
            className="flex items-center gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1"
          >
            {TABS.map((item) => {
              const active = tab === item.key;
              const Icon = item.icon;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setTab(item.key)}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors",
                    active
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon aria-hidden="true" className="size-4" />
                  {item.label}
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground tabular-nums">
                    {item.key === "orders"
                      ? orders.length
                      : item.key === "contacts"
                        ? contacts.length
                        : ""}
                  </span>
                </button>
              );
            })}
          </nav>

          {tab === "orders" ? (
            <OrdersPanel
              orders={orders}
              canWrite={canWrite && customer.isActive}
              onNewOrder={() => router.push("/dashboard/erp/orders")}
              onOpenOrder={(order) => router.push(`/dashboard/erp/orders/${order.id}`)}
              columns={orderColumns}
            />
          ) : null}

          {tab === "contacts" ? (
            <ContactsPanel
              contacts={contacts}
              canWrite={canWrite}
              onAdd={() => setAddContactOpen(true)}
              onEdit={setEditingContact}
              onDeactivate={setDeactivatingContact}
            />
          ) : null}

          {tab === "notes" ? (
            <NotesCard entityType="customer" entityId={customerId} canWrite={canWrite} />
          ) : null}

          {tab === "timeline" ? (
            <TimelineCard entityType="customer" entityId={customerId} canWrite={canWrite} />
          ) : null}
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

      <ContactFormDialog
        open={addContactOpen}
        onOpenChange={setAddContactOpen}
        customers={[customer]}
        onSaved={async () => {
          setTab("contacts");
          await load();
        }}
      />

      <ContactFormDialog
        open={editingContact !== null}
        onOpenChange={(open) => !open && setEditingContact(null)}
        customers={[customer]}
        contact={editingContact}
        onSaved={async () => {
          setTab("contacts");
          await load();
        }}
      />

      <Dialog
        open={deactivatingContact !== null}
        onOpenChange={(open) => !open && setDeactivatingContact(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Deactivate {deactivatingContact ? contactName(deactivatingContact) : "contact"}?
            </DialogTitle>
            <DialogDescription>
              The contact can no longer be selected and drops out of the active contacts list.
              Timeline history stays intact.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeactivatingContact(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void onDeactivateContact()}
              disabled={busy}
            >
              {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Deactivate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PanelShell({
  title,
  icon: Icon,
  action,
  children,
}: {
  title: string;
  icon: typeof ShoppingCart;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
          <Icon aria-hidden="true" className="size-4 text-primary" />
          {title}
        </h3>
        {action}
      </div>
      {children}
    </div>
  );
}

function OrdersPanel({
  orders,
  canWrite,
  onNewOrder,
  onOpenOrder,
  columns,
}: {
  orders: SalesOrder[];
  canWrite: boolean;
  onNewOrder: () => void;
  onOpenOrder: (order: SalesOrder) => void;
  columns: ErpColumn<SalesOrder>[];
}) {
  return (
    <PanelShell
      title="Order history"
      icon={ShoppingCart}
      action={
        canWrite ? (
          <Button type="button" size="sm" onClick={onNewOrder}>
            <Plus aria-hidden="true" className="size-4" />
            New order
          </Button>
        ) : undefined
      }
    >
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
          onRowClick={onOpenOrder}
        />
      )}
    </PanelShell>
  );
}

function ContactsPanel({
  contacts,
  canWrite,
  onAdd,
  onEdit,
  onDeactivate,
}: {
  contacts: Contact[];
  canWrite: boolean;
  onAdd: () => void;
  onEdit: (contact: Contact) => void;
  onDeactivate: (contact: Contact) => void;
}) {
  if (contacts.length === 0) {
    return (
      <PanelShell
        title="Contacts"
        icon={ContactRound}
        action={
          canWrite ? (
            <Button type="button" size="sm" onClick={onAdd}>
              <Plus aria-hidden="true" className="size-4" />
              Add contact
            </Button>
          ) : undefined
        }
      >
        <EmptyState
          icon={ContactRound}
          title="No contacts yet"
          description="Add the people on this account — they anchor activities and notes."
        />
      </PanelShell>
    );
  }

  return (
    <PanelShell
      title="Contacts"
      icon={ContactRound}
      action={
        canWrite ? (
          <Button type="button" size="sm" onClick={onAdd}>
            <Plus aria-hidden="true" className="size-4" />
            Add contact
          </Button>
        ) : undefined
      }
    >
      <ul className="divide-y divide-border/60 overflow-hidden rounded-xl border border-border bg-card">
        {contacts.map((contact) => (
          <li
            key={contact.id}
            className="flex items-center justify-between gap-3 px-4 py-3 last:border-0"
          >
            <div className="min-w-0">
              <p className="flex items-center gap-2 truncate font-medium text-foreground">
                {contactName(contact)}
                {contact.isPrimary ? (
                  <Badge
                    variant="outline"
                    className="shrink-0 bg-primary/10 text-primary ring-1 ring-primary/30"
                  >
                    Primary
                  </Badge>
                ) : null}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {[contact.jobTitle, contact.email, contact.phone].filter(Boolean).join(" · ") ||
                  "No contact details"}
              </p>
            </div>
            {canWrite ? (
              <div className="flex shrink-0 items-center gap-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Edit contact"
                  title="Edit contact"
                  onClick={() => onEdit(contact)}
                >
                  <Pencil aria-hidden="true" className="size-3.5 text-muted-foreground" />
                </Button>
                {contact.isActive ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Deactivate contact"
                    title="Deactivate"
                    onClick={() => onDeactivate(contact)}
                  >
                    <UserX aria-hidden="true" className="size-3.5 text-muted-foreground" />
                  </Button>
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </PanelShell>
  );
}

