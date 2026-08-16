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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { type Employee } from "@/lib/api/hr-api";import { createCompensationChange } from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";
import { formatDate } from "@/lib/format";

interface RecordState {
  employeeId: string;
  effectiveFrom: string;
  monthlySalary: string;
  currency: string;
}

/**
 * Record a compensation change. When `picker` is true the employee is chosen
 * inside the dialog (used by the payroll home checklist); otherwise the caller
 * supplies `defaultEmployeeId` (used by the compensation page).
 */
export function CompensationDialog({
  open,
  onOpenChange,
  employees,
  picker,
  defaultEmployeeId,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employees: Employee[];
  picker?: boolean;
  defaultEmployeeId?: string;
  onSaved: (message: string) => void;
}) {
  const [record, setRecord] = useState<RecordState>({
    employeeId: "",
    effectiveFrom: "",
    monthlySalary: "",
    currency: "USD",
  });
  const [recordError, setRecordError] = useState<string | null>(null);
  const [recordSaving, setRecordSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRecord({
      employeeId: defaultEmployeeId ?? "",
      effectiveFrom: "",
      monthlySalary: "",
      currency: "USD",
    });
    setRecordError(null);
  }, [open, defaultEmployeeId]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (recordSaving) return;
    if (!record.employeeId) {
      setRecordError("Choose an employee.");
      return;
    }
    if (!record.effectiveFrom || !record.monthlySalary.trim()) {
      setRecordError("Effective date and monthly salary are required.");
      return;
    }
    if (!Number.isFinite(Number(record.monthlySalary))) {
      setRecordError("Monthly salary must be a number.");
      return;
    }
    if (!/^[A-Za-z]{3}$/.test(record.currency)) {
      setRecordError("Currency must be a 3-letter code.");
      return;
    }
    setRecordSaving(true);
    setRecordError(null);
    try {
      const entry = await createCompensationChange({
        employeeId: record.employeeId,
        effectiveFrom: record.effectiveFrom,
        monthlySalary: record.monthlySalary.trim(),
        currency: record.currency.toUpperCase(),
      });
      onOpenChange(false);
      onSaved(`Compensation change recorded (${formatDate(entry.effectiveFrom)}).`);
    } catch (error) {
      setRecordError(
        error instanceof ApiError ? error.message : "Could not record the change.",
      );
    } finally {
      setRecordSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !recordSaving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={(event) => void onSubmit(event)}>
          <DialogHeader>
            <DialogTitle>Record compensation change</DialogTitle>
            <DialogDescription>
              Set a new monthly salary for the selected employee. The current
              rate stops on the effective date.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            {picker ? (
              <div className="space-y-1.5">
                <Label htmlFor="record-employee">Employee</Label>
                <Select
                  value={record.employeeId}
                  onValueChange={(value) =>
                    setRecord((current) => ({ ...current, employeeId: value }))
                  }
                >
                  <SelectTrigger id="record-employee" className="w-full">
                    <SelectValue placeholder="Choose an employee" />
                  </SelectTrigger>
                  <SelectContent>
                    {employees.map((employee) => (
                      <SelectItem key={employee.id} value={employee.id}>
                        {employee.firstName} {employee.lastName}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label htmlFor="record-effective">Effective date</Label>
              <Input
                id="record-effective"
                type="date"
                value={record.effectiveFrom}
                onChange={(event) =>
                  setRecord((current) => ({ ...current, effectiveFrom: event.target.value }))
                }
                required
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_6rem]">
              <div className="space-y-1.5">
                <Label htmlFor="record-salary">Monthly salary</Label>
                <Input
                  id="record-salary"
                  inputMode="decimal"
                  placeholder="5000.00"
                  value={record.monthlySalary}
                  onChange={(event) =>
                    setRecord((current) => ({
                      ...current,
                      monthlySalary: event.target.value,
                    }))
                  }
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="record-currency">Currency</Label>
                <Input
                  id="record-currency"
                  maxLength={3}
                  className="uppercase"
                  value={record.currency}
                  onChange={(event) =>
                    setRecord((current) => ({
                      ...current,
                      currency: event.target.value.toUpperCase(),
                    }))
                  }
                />
              </div>
            </div>
          </div>
          {recordError ? (
            <p role="alert" className="mb-2 text-sm font-medium text-destructive">
              {recordError}
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={recordSaving}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={recordSaving}>
              {recordSaving ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : null}
              Record change
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
