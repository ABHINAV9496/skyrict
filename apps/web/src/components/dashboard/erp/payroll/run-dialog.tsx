"use client";

import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DatePicker } from "@/components/ui/date-picker";
import { Label } from "@/components/ui/label";
import { createPayrollRun, type PayrollRun } from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";

interface RunFormState {
  periodStart: string;
  periodEnd: string;
}

const EMPTY_FORM: RunFormState = { periodStart: "", periodEnd: "" };

/** Create a payroll run as a draft for the given pay period. */
export function NewRunDialog({
  open,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (run: PayrollRun, message: string) => void;
}) {
  const [form, setForm] = useState<RunFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY_FORM);
    setFormError(null);
  }, [open]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (!form.periodStart || !form.periodEnd) {
      setFormError("Both a start and an end date are required.");
      return;
    }
    if (form.periodEnd < form.periodStart) {
      setFormError("The end date can't be before the start date.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const run = await createPayrollRun({
        periodStart: form.periodStart,
        periodEnd: form.periodEnd,
      });
      onOpenChange(false);
      onSaved(run, `${run.runCode} created as a draft.`);
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : "Could not create the run.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={(event) => void onSubmit(event)}>
          <DialogHeader>
            <DialogTitle>New payroll run</DialogTitle>
            <DialogDescription>
              Pick the pay period. The run starts as a draft so you can review
              it before computing.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="period-start">Period start</Label>
              <DatePicker
                id="period-start"
                value={form.periodStart || null}
                onChange={(iso) =>
                  setForm((current) => ({ ...current, periodStart: iso ?? "" }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="period-end">Period end</Label>
              <DatePicker
                id="period-end"
                value={form.periodEnd || null}
                onChange={(iso) =>
                  setForm((current) => ({ ...current, periodEnd: iso ?? "" }))
                }
                required
              />
            </div>
          </div>
          {formError ? (
            <p role="alert" className="mb-2 text-sm font-medium text-destructive">
              {formError}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Create run
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
