"use client";

import { useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { createLeaveRequest, type Employee } from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";

const LEAVE_TYPES = [
  { value: "annual", label: "Annual" },
  { value: "sick", label: "Sick" },
  { value: "unpaid", label: "Unpaid" },
] as const;

type FormState = {
  employeeId: string;
  leaveType: string;
  startDate: string;
  endDate: string;
  reason: string;
};

const EMPTY_FORM: FormState = {
  employeeId: "",
  leaveType: "",
  startDate: "",
  endDate: "",
  reason: "",
};

function typeCallout(leaveType: string): string | null {
  if (leaveType === "unpaid") {
    return "This unpaid leave will reduce the employee\u2019s pay for the affected period.";
  }
  if (leaveType === "annual" || leaveType === "sick") {
    return "This leave will be deducted from the employee\u2019s balance upon approval.";
  }
  return null;
}

interface LogLeaveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employees: Employee[];
  prefillEmployeeId?: string | null;
  onCreated?: () => void;
}

export function LogLeaveDialog({
  open,
  onOpenChange,
  employees,
  prefillEmployeeId,
  onCreated,
}: LogLeaveDialogProps) {
  const [form, setForm] = useState<FormState>(() => ({
    ...EMPTY_FORM,
    employeeId: prefillEmployeeId ?? "",
  }));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleClose(nextOpen: boolean) {
    if (saving) return;
    if (!nextOpen) {
      setForm({ ...EMPTY_FORM, employeeId: prefillEmployeeId ?? "" });
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
    if (!form.leaveType) {
      setError("Leave type is required.");
      return;
    }
    if (!form.startDate || !form.endDate) {
      setError("Start and end dates are required.");
      return;
    }
    if (form.endDate < form.startDate) {
      setError("End date cannot be before start date.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await createLeaveRequest({
        employeeId: form.employeeId,
        leaveType: form.leaveType,
        startDate: form.startDate,
        endDate: form.endDate,
        reason: form.reason.trim() || undefined,
      });
      handleClose(false);
      onCreated?.();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not create leave request.",
      );
    } finally {
      setSaving(false);
    }
  }

  const callout = typeCallout(form.leaveType);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={(e) => void onSubmit(e)}>
          <DialogHeader>
            <DialogTitle>Log leave</DialogTitle>
            <DialogDescription>
              Create a leave request on behalf of an employee.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="log-employee">Employee</Label>
              <Select
                value={form.employeeId}
                onValueChange={(value) => updateField("employeeId", value)}
                disabled={!!prefillEmployeeId}
              >
                <SelectTrigger id="log-employee" className="w-full">
                  <SelectValue placeholder="Select employee" />
                </SelectTrigger>
                <SelectContent>
                  {employees.map((emp) => (
                    <SelectItem key={emp.id} value={emp.id}>
                      {emp.firstName} {emp.lastName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="log-type">Leave type</Label>
              <Select
                value={form.leaveType}
                onValueChange={(value) => updateField("leaveType", value)}
              >
                <SelectTrigger id="log-type" className="w-full">
                  <SelectValue placeholder="Select type" />
                </SelectTrigger>
                <SelectContent>
                  {LEAVE_TYPES.map((lt) => (
                    <SelectItem key={lt.value} value={lt.value}>
                      {lt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label htmlFor="log-start">Start date</Label>
                <Input
                  id="log-start"
                  type="date"
                  value={form.startDate}
                  onChange={(e) => updateField("startDate", e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="log-end">End date</Label>
                <Input
                  id="log-end"
                  type="date"
                  value={form.endDate}
                  onChange={(e) => updateField("endDate", e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="log-reason">Reason (optional)</Label>
              <Input
                id="log-reason"
                value={form.reason}
                onChange={(e) => updateField("reason", e.target.value)}
                placeholder="e.g. Medical appointment"
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
              Create request
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
