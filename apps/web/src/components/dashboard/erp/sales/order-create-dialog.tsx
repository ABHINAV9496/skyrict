"use client";

import { useCallback, useEffect, useState } from "react";
import { LoaderCircle, Plus, ShoppingCart, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  createOrder,
  listCustomers,
  listProducts,
  type Customer,
  type Product,
  type SalesOrder,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { formatMoney } from "@/lib/erp/money";

interface OrderCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (order: SalesOrder) => void;
}

interface LineRow {
  key: string;
  productId: string;
  quantity: string;
}

type LoadStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; customers: Customer[]; products: Product[] };

function nextLineKey(): string {
  return `line-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Create-order dialog. Fetches active customers and sellable products when it
 * opens, then builds a line item per product. Submitting is pessimistic -
 * the button disables while the order is being created and errors render
 * inline instead of closing the dialog.
 */
export function OrderCreateDialog({ open, onOpenChange, onCreated }: OrderCreateDialogProps) {
  const [loadStatus, setLoadStatus] = useState<LoadStatus>({ state: "loading" });
  const [customerId, setCustomerId] = useState("");
  const [lines, setLines] = useState<LineRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadStatus({ state: "loading" });
    try {
      const [customersResult, productsResult] = await Promise.all([
        listCustomers({ limit: 100 }),
        listProducts({ limit: 100 }),
      ]);
      setLoadStatus({
        state: "ready",
        customers: customersResult.data.filter((customer) => customer.isActive),
        products: productsResult.data.filter((product) => product.isActive),
      });
    } catch (error) {
      setLoadStatus({
        state: "error",
        message:
          error instanceof ApiError
            ? error.message
            : "Could not load customers and products.",
      });
    }
  }, []);

  useEffect(() => {
    if (open) {
      setCustomerId("");
      setLines([{ key: nextLineKey(), productId: "", quantity: "1" }]);
      setSaving(false);
      setNotice(null);
      void load();
    }
  }, [open, load]);

  function addLine() {
    setLines((current) => [...current, { key: nextLineKey(), productId: "", quantity: "1" }]);
  }

  function updateLine(key: string, changes: Partial<Pick<LineRow, "productId" | "quantity">>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...changes } : line)),
    );
  }

  function removeLine(key: string) {
    setLines((current) =>
      current.length > 1 ? current.filter((line) => line.key !== key) : current,
    );
  }

  const validLines = lines.filter((line) => line.productId && Number(line.quantity) > 0);
  const canSubmit = Boolean(customerId) && validLines.length > 0 && !saving;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

    setSaving(true);
    setNotice(null);
    try {
      const order = await createOrder({
        customerId,
        lines: validLines.map((line) => ({
          productId: line.productId,
          quantity: String(Number(line.quantity)),
        })),
      });
      onCreated(order);
      onOpenChange(false);
    } catch (error) {
      setNotice(
        error instanceof ApiError ? error.message : "Could not create the order.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShoppingCart aria-hidden="true" className="size-4 text-primary" />
            New order
          </DialogTitle>
          <DialogDescription>
            Pick a customer and add line items. The order starts as a draft and is priced by the
            backend.
          </DialogDescription>
        </DialogHeader>

        {loadStatus.state === "loading" ? (
          <div className="space-y-3">
            <div className="h-8 w-full rounded-lg bg-muted/70" />
            <div className="h-24 rounded-lg bg-muted/70" />
          </div>
        ) : loadStatus.state === "error" ? (
          <div className="space-y-3">
            <div
              role="alert"
              className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
            >
              {loadStatus.message}
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => void load()}>
              Try again
            </Button>
          </div>
        ) : loadStatus.customers.length === 0 || loadStatus.products.length === 0 ? (
          <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
            {loadStatus.customers.length === 0
              ? "There are no active customers yet - create one in CRM first."
              : "There are no active products yet."}
          </p>
        ) : (
          <form id="order-form" onSubmit={(event) => void onSubmit(event)} className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="order-customer">Customer</Label>
              <Select value={customerId} onValueChange={setCustomerId} disabled={saving}>
                <SelectTrigger id="order-customer" className="w-full">
                  <SelectValue placeholder="Select a customer" />
                </SelectTrigger>
                <SelectContent>
                  {loadStatus.customers.map((customer) => (
                    <SelectItem key={customer.id} value={customer.id}>
                      {customer.name} {customer.customerCode ? `(${customer.customerCode})` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label>Line items</Label>
                <Button type="button" variant="outline" size="sm" onClick={addLine} disabled={saving}>
                  <Plus aria-hidden="true" className="size-3.5" />
                  Add line
                </Button>
              </div>

              <div className="space-y-2">
                {lines.map((line, index) => {
                  return (
                    <div key={line.key} className="flex items-center gap-2">
                      <span className="w-6 shrink-0 text-center text-xs text-muted-foreground tabular-nums">
                        {index + 1}
                      </span>
                      <Select
                        value={line.productId || undefined}
                        onValueChange={(value) => updateLine(line.key, { productId: value })}
                        disabled={saving}
                      >
                        <SelectTrigger className="w-full" aria-label={`Product for line ${index + 1}`}>
                          <SelectValue placeholder="Select a product" />
                        </SelectTrigger>
                        <SelectContent>
                          {loadStatus.products.map((item) => (
                            <SelectItem key={item.id} value={item.id}>
                              {item.name}
                              <span className="ml-2 text-muted-foreground">
                                ({formatMoney(item.sellPrice)} / {item.unit || "unit"})
                              </span>
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Input
                        type="number"
                        min="1"
                        step="1"
                        value={line.quantity}
                        onChange={(event) => updateLine(line.key, { quantity: event.target.value })}
                        className="w-20 shrink-0"
                        aria-label={`Quantity for line ${index + 1}`}
                        disabled={saving}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label={`Remove line ${index + 1}`}
                        onClick={() => removeLine(line.key)}
                        disabled={saving || lines.length === 1}
                      >
                        <Trash2 aria-hidden="true" className="size-3.5 text-muted-foreground" />
                      </Button>
                    </div>
                  );
                })}
              </div>
            </div>

            {notice ? (
              <div
                role="alert"
                className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
              >
                {notice}
              </div>
            ) : null}
          </form>
        )}

        {loadStatus.state === "ready" &&
        loadStatus.customers.length > 0 &&
        loadStatus.products.length > 0 ? (
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" form="order-form" disabled={!canSubmit}>
              {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Create draft order
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
