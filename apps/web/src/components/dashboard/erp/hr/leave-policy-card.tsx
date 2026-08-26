"use client";

import { useCallback, useState } from "react";
import { LoaderCircle, Settings } from "lucide-react";

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
import { getLeavePolicy, updateLeavePolicy, type LeavePolicy } from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDate } from "@/lib/format";

interface LeavePolicyCardProps {
  policy: LeavePolicy | null;
  canEdit: boolean;
  onPolicyUpdated: (policy: LeavePolicy) => void;
}

export function LeavePolicyCard({ policy, canEdit, onPolicyUpdated }: LeavePolicyCardProps) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    casualDaysPerYear: policy?.casualDaysPerYear ?? 12,
    sickDaysPerYear: policy?.sickDaysPerYear ?? 8,
    effectiveFrom: policy?.effectiveFrom ?? new Date().toISOString().slice(0, 10),
  });

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateLeavePolicy({
        casualDaysPerYear: form.casualDaysPerYear,
        sickDaysPerYear: form.sickDaysPerYear,
        effectiveFrom: form.effectiveFrom,
      });
      onPolicyUpdated(updated);
      setOpen(false);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Failed to update policy");
      }
    } finally {
      setSaving(false);
    }
  }, [form, onPolicyUpdated]);

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Settings className="size-4 text-muted-foreground" />
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            Leave Policy
          </h2>
        </div>
        {canEdit ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setOpen(true)}
          >
            Edit Policy
          </Button>
        ) : null}
      </div>

      {policy ? (
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">Casual Leave</p>
            <p className="text-lg font-semibold text-foreground">{policy.casualDaysPerYear} days/year</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Sick Leave</p>
            <p className="text-lg font-semibold text-foreground">{policy.sickDaysPerYear} days/year</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Effective From</p>
            <p className="text-lg font-semibold text-foreground">{formatDate(policy.effectiveFrom)}</p>
          </div>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">
          No leave policy configured. Set one to enable casual and sick leave accruals.
        </p>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit Leave Policy</DialogTitle>
            <DialogDescription>
              Changes take effect at the next Jan-1 reset. Policy changes do not
              retroactively alter existing balances.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleSave();
            }}
            className="space-y-4"
          >
            <div className="space-y-1.5">
              <Label htmlFor="casual-days">Casual Leave (days/year)</Label>
              <Input
                id="casual-days"
                type="number"
                min={0}
                value={form.casualDaysPerYear}
                onChange={(e) =>
                  setForm((f) => ({ ...f, casualDaysPerYear: Number(e.target.value) }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sick-days">Sick Leave (days/year)</Label>
              <Input
                id="sick-days"
                type="number"
                min={0}
                value={form.sickDaysPerYear}
                onChange={(e) =>
                  setForm((f) => ({ ...f, sickDaysPerYear: Number(e.target.value) }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="effective-from">Effective From</Label>
              <Input
                id="effective-from"
                type="date"
                value={form.effectiveFrom}
                onChange={(e) =>
                  setForm((f) => ({ ...f, effectiveFrom: e.target.value }))
                }
                required
              />
            </div>
            {error ? (
              <p role="alert" className="text-sm font-medium text-destructive">
                {error}
              </p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : null}
                Save Policy
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
