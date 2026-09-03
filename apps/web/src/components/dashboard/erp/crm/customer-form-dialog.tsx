"use client";

import { useEffect, useState } from "react";
import { Building2, LoaderCircle, UserPlus } from "lucide-react";

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
import { createCustomer, updateCustomer, type Customer } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

interface CustomerFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (customer: Customer) => void;
  /** When provided the dialog edits this customer instead of creating one. */
  customer?: Customer | null;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Create/edit customer dialog. Pessimistic submit: disables while in flight,
 * server errors render inline, and the dialog only closes on success.
 */
export function CustomerFormDialog({
  open,
  onOpenChange,
  onSaved,
  customer,
}: CustomerFormDialogProps) {
  const editing = Boolean(customer);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [creditLimit, setCreditLimit] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (open) {
      setName(customer?.name ?? "");
      setEmail(customer?.email ?? "");
      setPhone(customer?.phone ?? "");
      setCreditLimit(customer?.creditLimit ?? "");
      setCurrency(customer?.currency ?? "USD");
      setSaving(false);
      setNotice(null);
    }
  }, [open, customer]);

  const canSubmit = name.trim().length > 0 && !saving;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

    const trimmedEmail = email.trim();
    if (trimmedEmail && !EMAIL_PATTERN.test(trimmedEmail)) {
      setNotice({ tone: "error", text: "Enter a valid email address." });
      return;
    }

    setSaving(true);
    setNotice(null);
    try {
      const input = {
        name: name.trim(),
        email: trimmedEmail || undefined,
        phone: phone.trim() || undefined,
        creditLimit: creditLimit.trim() || undefined,
        currency,
      };
      const saved = editing && customer
        ? await updateCustomer(customer.id, input)
        : await createCustomer(input);
      setNotice({ tone: "success", text: editing ? "Customer updated." : "Customer created." });
      onSaved(saved);
      onOpenChange(false);
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError
            ? error.message
            : editing
              ? "Could not update the customer."
              : "Could not create the customer.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {editing ? (
              <Building2 aria-hidden="true" className="size-4 text-primary" />
            ) : (
              <UserPlus aria-hidden="true" className="size-4 text-primary" />
            )}
            {editing ? "Edit customer" : "New customer"}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? "Update the customer profile. Changes apply immediately."
              : "Create a customer manually. Customers also arrive from won opportunities."}
          </DialogDescription>
        </DialogHeader>

        <form id="customer-form" onSubmit={(event) => void onSubmit(event)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="customer-name">Name</Label>
            <Input
              id="customer-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Northwind Traders"
              maxLength={255}
              disabled={saving}
              aria-required="true"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="customer-email">Email</Label>
              <Input
                id="customer-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="billing@company.com"
                maxLength={320}
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="customer-phone">Phone</Label>
              <Input
                id="customer-phone"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="+1 555 010 2030"
                maxLength={32}
                disabled={saving}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="customer-credit-limit">Credit limit</Label>
              <Input
                id="customer-credit-limit"
                type="number"
                min="0"
                step="0.01"
                value={creditLimit}
                onChange={(event) => setCreditLimit(event.target.value)}
                placeholder="0.00"
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="customer-currency">Currency</Label>
              <Select value={currency} onValueChange={setCurrency} disabled={saving}>
                <SelectTrigger id="customer-currency" className="w-full">
                  <SelectValue placeholder="USD" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="USD">USD - US dollar</SelectItem>
                  <SelectItem value="EUR">EUR - Euro</SelectItem>
                  <SelectItem value="GBP">GBP - British pound</SelectItem>
                  <SelectItem value="INR">INR - Indian rupee</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {notice ? (
            <div
              role={notice.tone === "error" ? "alert" : "status"}
              className={cn(
                "rounded-lg border px-3 py-2 text-sm font-medium",
                notice.tone === "error"
                  ? "border-destructive/40 bg-destructive/5 text-destructive"
                  : "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
              )}
            >
              {notice.text}
            </div>
          ) : null}
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="customer-form" disabled={!canSubmit}>
            {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
            {editing ? "Save changes" : "Create customer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
