"use client";

import { useEffect, useState } from "react";
import { Leaf, LoaderCircle, Trash2, UserCheck } from "lucide-react";

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
  changeEmployeeStatus,
  createEmployee,
  terminateEmployee,
  updateEmployee,
  type Department,
  type Employee,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";

interface EmployeeFormState {
  firstName: string;
  lastName: string;
  jobTitle: string;
  hireDate: string;
  email: string;
  phone: string;
  departmentId: string;
  monthlySalary: string;
  currency: string;
}

const EMPTY_FORM: EmployeeFormState = {
  firstName: "",
  lastName: "",
  jobTitle: "",
  hireDate: "",
  email: "",
  phone: "",
  departmentId: "",
  monthlySalary: "",
  currency: "USD",
};

export function EmployeeFormDialog({
  open,
  onOpenChange,
  departments,
  employee,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  departments: Department[];
  employee: Employee | null;
  onSaved: (employee: Employee, message: string) => void;
}) {
  const [form, setForm] = useState<EmployeeFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(
      employee
        ? {
            firstName: employee.firstName,
            lastName: employee.lastName,
            jobTitle: employee.jobTitle,
            hireDate: employee.hireDate,
            email: employee.email ?? "",
            phone: employee.phone ?? "",
            departmentId: employee.departmentId ?? "",
            monthlySalary: "",
            currency: "USD",
          }
        : EMPTY_FORM,
    );
    setFormError(null);
  }, [open, employee]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (!form.firstName.trim() || !form.lastName.trim() || !form.jobTitle.trim()) {
      setFormError("First name, last name, and job title are required.");
      return;
    }
    if (!form.hireDate) {
      setFormError("A hire date is required.");
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      if (employee) {
        const updated = await updateEmployee(employee.id, {
          firstName: form.firstName.trim(),
          lastName: form.lastName.trim(),
          jobTitle: form.jobTitle.trim(),
          hireDate: form.hireDate,
          email: form.email.trim() || undefined,
          phone: form.phone.trim() || undefined,
          departmentId: form.departmentId || undefined,
        });
        onOpenChange(false);
        onSaved(updated, `${updated.firstName} ${updated.lastName} updated.`);
      } else {
        const created = await createEmployee({
          firstName: form.firstName.trim(),
          lastName: form.lastName.trim(),
          jobTitle: form.jobTitle.trim(),
          hireDate: form.hireDate,
          email: form.email.trim() || undefined,
          phone: form.phone.trim() || undefined,
          departmentId: form.departmentId || undefined,
          monthlySalary: form.monthlySalary.trim() || undefined,
          currency: form.currency.trim() || undefined,
        });
        onOpenChange(false);
        onSaved(created, `${created.firstName} ${created.lastName} hired.`);
      }
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : "Could not save the employee.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={(event) => void onSubmit(event)}>
          <DialogHeader>
            <DialogTitle>
              {employee ? "Edit employee" : "Hire a new employee"}
            </DialogTitle>
            <DialogDescription>
              {employee
                ? "Update the employee's profile details."
                : "Create the employee record. Compensation is set from Payroll."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="first-name">First name</Label>
              <Input
                id="first-name"
                value={form.firstName}
                onChange={(event) =>
                  setForm((current) => ({ ...current, firstName: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="last-name">Last name</Label>
              <Input
                id="last-name"
                value={form.lastName}
                onChange={(event) =>
                  setForm((current) => ({ ...current, lastName: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="job-title">Job title</Label>
              <Input
                id="job-title"
                value={form.jobTitle}
                onChange={(event) =>
                  setForm((current) => ({ ...current, jobTitle: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="hire-date">Hire date</Label>
              <Input
                id="hire-date"
                type="date"
                value={form.hireDate}
                onChange={(event) =>
                  setForm((current) => ({ ...current, hireDate: event.target.value }))
                }
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                onChange={(event) =>
                  setForm((current) => ({ ...current, email: event.target.value }))
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="phone">Phone</Label>
              <Input
                id="phone"
                value={form.phone}
                onChange={(event) =>
                  setForm((current) => ({ ...current, phone: event.target.value }))
                }
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="department">Department</Label>
              <Select
                value={form.departmentId}
                onValueChange={(value) =>
                  setForm((current) => ({ ...current, departmentId: value }))
                }
              >
                <SelectTrigger id="department" className="w-full">
                  <SelectValue placeholder="No department" />
                </SelectTrigger>
                <SelectContent>
                  {departments.map((department) => (
                    <SelectItem key={department.id} value={department.id}>
                      {department.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {!employee ? (
              <div className="grid gap-3 sm:col-span-2 sm:grid-cols-[1fr_6rem]">
                <div className="space-y-1.5">
                  <Label htmlFor="monthly-salary">Monthly salary (optional)</Label>
                  <Input
                    id="monthly-salary"
                    inputMode="decimal"
                    placeholder="5000.00"
                    value={form.monthlySalary}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        monthlySalary: event.target.value,
                      }))
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="currency">Currency</Label>
                  <Input
                    id="currency"
                    maxLength={3}
                    className="uppercase"
                    value={form.currency}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        currency: event.target.value.toUpperCase(),
                      }))
                    }
                  />
                </div>
              </div>
            ) : null}
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
              {employee ? "Save changes" : "Hire employee"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function ChangeStatusDialog({
  employee,
  target,
  onOpenChange,
  onSaved,
}: {
  employee: Employee | null;
  target: "active" | "on_leave" | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (employee: Employee, message: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!employee) return;
    setError(null);
  }, [employee]);

  const leaving = target === "on_leave";
  const name = employee ? `${employee.firstName} ${employee.lastName}` : "";

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!employee || !target || saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await changeEmployeeStatus(employee.id, target);
      onOpenChange(false);
      onSaved(
        updated,
        leaving
          ? `${updated.firstName} ${updated.lastName} placed on leave.`
          : `${updated.firstName} ${updated.lastName} reactivated.`,
      );
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not update the employee status.",
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={employee !== null && target !== null}
      onOpenChange={(next) => !saving && onOpenChange(next)}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={(event) => void onSubmit(event)}>
          <DialogHeader>
            <DialogTitle>
              {leaving ? `Place ${name} on leave?` : `Reactivate ${name}?`}
            </DialogTitle>
            <DialogDescription>
              {leaving
                ? "This moves the employee to on leave status. Their payroll entries and leave balances stay intact, and they can be reactivated later."
                : "This moves the employee back to active status so they can join future payroll runs."}
            </DialogDescription>
          </DialogHeader>
          {error ? (
            <p role="alert" className="mt-4 text-sm font-medium text-destructive">
              {error}
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
              ) : leaving ? (
                <Leaf aria-hidden="true" className="size-4" />
              ) : (
                <UserCheck aria-hidden="true" className="size-4" />
              )}
              {leaving ? "Place on leave" : "Reactivate"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function TerminateEmployeeDialog({
  employee,
  onOpenChange,
  onSaved,
}: {
  employee: Employee | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (employee: Employee, message: string) => void;
}) {
  const [terminationDate, setTerminationDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!employee) return;
    setTerminationDate("");
    setReason("");
    setError(null);
  }, [employee]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!employee || saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await terminateEmployee(employee.id, {
        terminationDate: terminationDate || undefined,
        reason: reason.trim() || undefined,
      });
      onOpenChange(false);
      onSaved(updated, `${updated.firstName} ${updated.lastName} terminated.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not terminate the employee.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={employee !== null}
      onOpenChange={(next) => !saving && onOpenChange(next)}
    >
      <DialogContent className="sm:max-w-md">
        <form onSubmit={(event) => void onSubmit(event)}>
          <DialogHeader>
            <DialogTitle>
              Terminate {employee?.firstName} {employee?.lastName}?
            </DialogTitle>
            <DialogDescription>
              This moves the employee to{" "}
              <span className="font-medium">terminated</span> status. It
              can&apos;t be undone from this screen.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="termination-date">Termination date (optional)</Label>
              <Input
                id="termination-date"
                type="date"
                value={terminationDate}
                onChange={(event) => setTerminationDate(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="termination-reason">Reason (optional)</Label>
              <Input
                id="termination-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. Role eliminated"
              />
            </div>
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
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" variant="destructive" disabled={saving}>
              {saving ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <Trash2 aria-hidden="true" className="size-4" />
              )}
              Terminate
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
