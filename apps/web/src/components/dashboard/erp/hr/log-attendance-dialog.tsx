"use client";

import { useMemo, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SearchableSelect } from "@/components/dashboard/shared/searchable-select";
import {
  byEmployeeName,
  employeeName,
  upsertAttendance,
  type AttendanceStatus,
  type Employee,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";

const STATUS_OPTIONS: { value: AttendanceStatus; label: string }[] = [
  { value: "on_time", label: "On time" },
  { value: "late", label: "Late" },
  { value: "absent", label: "Absent" },
];

type FormState = {
  employeeId: string;
  workDate: string;
  status: AttendanceStatus | "";
  note: string;
};

const EMPTY_FORM: FormState = {
  employeeId: "",
  workDate: "",
  status: "",
  note: "",
};

function impactCallout(status: AttendanceStatus | ""): string | null {
  if (status === "late") {
    return "A late arrival pays half of the day\u2019s rate.";
  }
  if (status === "absent") {
    return "An absent day pays nothing for the affected date.";
  }
  return null;
}

interface LogAttendanceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employees: Employee[];
  prefillEmployeeId?: string | null;
  defaultDate?: string;
  onSaved?: () => void;
}

export function LogAttendanceDialog({
  open,
  onOpenChange,
  employees,
  prefillEmployeeId,
  defaultDate,
  onSaved,
}: LogAttendanceDialogProps) {
  const [form, setForm] = useState<FormState>(() => ({
    ...EMPTY_FORM,
    employeeId: prefillEmployeeId ?? "",
    workDate: defaultDate ?? "",
    status: "on_time",
  }));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const employeeOptions = useMemo(
    () =>
      [...employees]
        .sort(byEmployeeName)
        .map((employee) => ({
          value: employee.id,
          label: employeeName(employee),
          keywords: employee.employeeNumber,
        })),
    [employees],
  );

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleClose(nextOpen: boolean) {
    if (saving) return;
    if (!nextOpen) {
      setForm({
        ...EMPTY_FORM,
        employeeId: prefillEmployeeId ?? "",
        workDate: defaultDate ?? "",
        status: "on_time",
      });
      setError(null);
    }
    onOpenChange(nextOpen);
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;

    if (!form.employeeId) {
      setError("Employee is required.");
      return;
    }
    if (!form.workDate) {
      setError("Work date is required.");
      return;
    }
    if (!form.status) {
      setError("Status is required.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await upsertAttendance({
        employeeId: form.employeeId,
        workDate: form.workDate,
        status: form.status,
        note: form.note.trim() || null,
      });
      handleClose(false);
      onSaved?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record attendance.");
    } finally {
      setSaving(false);
    }
  }

  const callout = impactCallout(form.status);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={(e) => void onSubmit(e)}>
          <DialogHeader>
            <DialogTitle>Log attendance</DialogTitle>
            <DialogDescription>
              Record or correct one work day. Logging the same day again
              overwrites the previous entry.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="attendance-employee">Employee</Label>
              <SearchableSelect
                id="attendance-employee"
                options={employeeOptions}
                value={form.employeeId || null}
                onValueChange={(value) => updateField("employeeId", value)}
                disabled={!!prefillEmployeeId}
                placeholder="Search employee"
                invalid={!form.employeeId && error !== null}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="attendance-date">Work date</Label>
              <DatePicker
                id="attendance-date"
                value={form.workDate || null}
                onChange={(iso) => updateField("workDate", iso ?? "")}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="attendance-status">Status</Label>
              <SearchableSelect
                id="attendance-status"
                options={STATUS_OPTIONS}
                value={form.status || null}
                onValueChange={(value) => updateField("status", value as AttendanceStatus)}
                placeholder="Select status"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="attendance-note">Note (optional)</Label>
              <Input
                id="attendance-note"
                value={form.note}
                onChange={(e) => updateField("note", e.target.value)}
                placeholder="e.g. Doctor appointment"
                maxLength={500}
              />
            </div>

            {callout ? (
              <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
                {callout}
              </p>
            ) : null}
          </div>

          {error ? (
            <p role="alert" className="mb-2 text-sm font-medium text-destructive">
              {error}
            </p>
          ) : null}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => handleClose(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Save attendance
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
