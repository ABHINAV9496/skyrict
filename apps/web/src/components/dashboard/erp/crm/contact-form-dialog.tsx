"use client";

import { useEffect, useState } from "react";
import { ContactRound, LoaderCircle, UserPlus } from "lucide-react";

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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createContact, updateContact, type Contact, type Customer } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

interface ContactFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (contact: Contact) => void;
  /** Customers for the create flow's required owner picker (fetched by the table). */
  customers: Customer[];
  /** When provided the dialog edits this contact instead of creating one. */
  contact?: Contact | null;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Create/edit contact dialog. Create requires picking the owning customer;
 * edit keeps the customer fixed (backend only sets it at creation). Pessimistic
 * submit with inline server errors, matching CustomerFormDialog.
 */
export function ContactFormDialog({
  open,
  onOpenChange,
  onSaved,
  customers,
  contact,
}: ContactFormDialogProps) {
  const editing = Boolean(contact);
  const [customerId, setCustomerId] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [isPrimary, setIsPrimary] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (open) {
      setCustomerId(contact?.customerId ?? "");
      setFirstName(contact?.firstName ?? "");
      setLastName(contact?.lastName ?? "");
      setEmail(contact?.email ?? "");
      setPhone(contact?.phone ?? "");
      setJobTitle(contact?.jobTitle ?? "");
      setIsPrimary(contact?.isPrimary ?? false);
      setSaving(false);
      setNotice(null);
    }
  }, [open, contact]);

  const hasName = firstName.trim().length > 0 || lastName.trim().length > 0;
  const canSubmit = !editing ? customerId.length > 0 && hasName && !saving : hasName && !saving;

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
        firstName: firstName.trim() || undefined,
        lastName: lastName.trim() || undefined,
        email: trimmedEmail || undefined,
        phone: phone.trim() || undefined,
        jobTitle: jobTitle.trim() || undefined,
        isPrimary,
      };
      const saved = editing && contact
        ? await updateContact(contact.id, input)
        : await createContact(customerId, input);
      setNotice({ tone: "success", text: editing ? "Contact updated." : "Contact created." });
      onSaved(saved);
      onOpenChange(false);
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError
            ? error.message
            : editing
              ? "Could not update the contact."
              : "Could not create the contact.",
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
              <ContactRound aria-hidden="true" className="size-4 text-primary" />
            ) : (
              <UserPlus aria-hidden="true" className="size-4 text-primary" />
            )}
            {editing ? "Edit contact" : "New contact"}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? "Update the contact's details. Changes apply immediately."
              : "Add a person on a customer account."}
          </DialogDescription>
        </DialogHeader>

        <form id="contact-form" onSubmit={(event) => void onSubmit(event)} className="space-y-4">
          {!editing ? (
            <div className="space-y-1.5">
              <Label htmlFor="contact-customer">Customer</Label>
              <Select value={customerId} onValueChange={setCustomerId} disabled={saving}>
                <SelectTrigger id="contact-customer" className="w-full">
                  <SelectValue placeholder="Select a customer" />
                </SelectTrigger>
                <SelectContent>
                  {customers.map((customer) => (
                    <SelectItem key={customer.id} value={customer.id}>
                      {customer.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="contact-first-name">First name</Label>
              <Input
                id="contact-first-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                placeholder="Jane"
                maxLength={100}
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="contact-last-name">Last name</Label>
              <Input
                id="contact-last-name"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                placeholder="Doe"
                maxLength={100}
                disabled={saving}
              />
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="contact-email">Email</Label>
              <Input
                id="contact-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="jane@company.com"
                maxLength={320}
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="contact-phone">Phone</Label>
              <Input
                id="contact-phone"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="+1 555 010 2030"
                maxLength={32}
                disabled={saving}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="contact-job-title">Job title</Label>
            <Input
              id="contact-job-title"
              value={jobTitle}
              onChange={(event) => setJobTitle(event.target.value)}
              placeholder="e.g. Procurement lead"
              maxLength={255}
              disabled={saving}
            />
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              id="contact-primary"
              checked={isPrimary}
              onCheckedChange={(checked) => setIsPrimary(checked === true)}
              disabled={saving}
            />
            <Label htmlFor="contact-primary" className="font-normal">
              Primary contact for this customer
            </Label>
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
          <Button type="submit" form="contact-form" disabled={!canSubmit}>
            {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
            {editing ? "Save changes" : "Create contact"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
