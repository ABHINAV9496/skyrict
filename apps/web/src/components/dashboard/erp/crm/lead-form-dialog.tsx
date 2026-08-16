"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, UserPlus } from "lucide-react";

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
import { createLead, type Lead } from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

interface LeadFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (lead: Lead) => void;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Create-lead dialog. Pessimistic: the submit button disables while the
 * request is in flight, and any server error surfaces inline as a notice.
 */
export function LeadFormDialog({ open, onOpenChange, onCreated }: LeadFormDialogProps) {
  const [source, setSource] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [company, setCompany] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [errorField, setErrorField] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setSource("");
      setFirstName("");
      setLastName("");
      setEmail("");
      setPhone("");
      setCompany("");
      setSaving(false);
      setNotice(null);
      setErrorField(null);
    }
  }, [open]);

  const contactName = `${firstName.trim()} ${lastName.trim()}`.trim();
  const canSubmit = Boolean(contactName || company.trim()) && !saving;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

    const trimmedEmail = email.trim();
    if (trimmedEmail && !EMAIL_PATTERN.test(trimmedEmail)) {
      setErrorField("email");
      setNotice({ tone: "error", text: "Enter a valid email address." });
      return;
    }

    setSaving(true);
    setNotice(null);
    setErrorField(null);
    try {
      const lead = await createLead({
        source: source.trim() || undefined,
        firstName: firstName.trim() || undefined,
        lastName: lastName.trim() || undefined,
        email: trimmedEmail || undefined,
        phone: phone.trim() || undefined,
        company: company.trim() || undefined,
      });
      setNotice({ tone: "success", text: "Lead created." });
      onCreated(lead);
      onOpenChange(false);
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not create the lead.",
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
            <UserPlus aria-hidden="true" className="size-4 text-primary" />
            New lead
          </DialogTitle>
          <DialogDescription>
            Capture an inbound inquiry. Qualifying it later creates an opportunity.
          </DialogDescription>
        </DialogHeader>

        <form id="lead-form" onSubmit={(event) => void onSubmit(event)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="lead-source">Source</Label>
            <Input
              id="lead-source"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="e.g. website"
              maxLength={64}
              disabled={saving}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="lead-first-name">First name</Label>
              <Input
                id="lead-first-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                placeholder="e.g. Ava"
                maxLength={128}
                disabled={saving}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lead-last-name">Last name</Label>
              <Input
                id="lead-last-name"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                placeholder="e.g. Whitmore"
                maxLength={128}
                disabled={saving}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="lead-company">Company</Label>
            <Input
              id="lead-company"
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              placeholder="e.g. Northwind Traders"
              maxLength={255}
              disabled={saving}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="lead-email">Email</Label>
              <Input
                id="lead-email"
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  if (errorField === "email") setErrorField(null);
                }}
                placeholder="ava@company.com"
                maxLength={320}
                disabled={saving}
                aria-invalid={errorField === "email" ? true : undefined}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="lead-phone">Phone</Label>
              <Input
                id="lead-phone"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="+1 555 010 2030"
                maxLength={32}
                disabled={saving}
              />
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
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button type="submit" form="lead-form" disabled={!canSubmit}>
            {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
            Create lead
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
