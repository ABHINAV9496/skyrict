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
import { CountryCombobox } from "@/components/dashboard/erp/hr/country-combobox";
import { getCountryByCode } from "@/lib/hr/countries";

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

/**
 * Seed values derived once from the browser locale when the hire dialog
 * opens: e.g. an en-IN browser suggests phone country "+91 IN" and currency
 * "INR". Unknown regions fall back to no phone country and USD. The two
 * fields stay fully independent after seeding.
 */
function localeDefaults(): { country: string | null; currency: string } {
  try {
    const region = new Intl.Locale(navigator.language).region;
    if (region && /^[A-Z]{2}$/.test(region)) {
      const country = getCountryByCode(region);
      if (country?.dialCode) {
        return { country: country.code, currency: country.currency ?? "USD" };
      }
    }
  } catch {
    // Invalid language tag or missing Intl.Locale support.
  }
  return { country: null, currency: "USD" };
}

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
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<"email" | "phone", string>>>({});
  const [selectedCountryCode, setSelectedCountryCode] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const selectedCountry = selectedCountryCode
    ? getCountryByCode(selectedCountryCode) ?? null
    : null;

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
    setFieldErrors({});
    setSelectedCountryCode(null);
    if (!employee) {
      const defaults = localeDefaults();
      setSelectedCountryCode(defaults.country);
      setForm((current) => ({ ...current, currency: defaults.currency }));
    }
  }, [open, employee]);

  /** Phone-side selection: updates only the phone country. */
  function handlePhoneCountryChange(code: string) {
    setSelectedCountryCode(code);
    setFieldErrors((current) => ({ ...current, phone: undefined }));
  }

  /** Currency-side selection: fully independent of the phone country. */
  function handleCurrencyChange(code: string) {
    setForm((current) => ({ ...current, currency: code }));
  }

  function validateHireFields(): boolean {
    const errors: Partial<Record<"email" | "phone", string>> = {};
    const email = form.email.trim();
    if (!email) {
      errors.email = "Email is required.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      errors.email = "Enter a valid email address.";
    }
    if (!form.phone.trim()) {
      errors.phone = "Phone number is required.";
    } else if (!selectedCountryCode) {
      errors.phone = "Select a country for the phone number.";
    } else if (
      selectedCountry?.phoneMin != null &&
      selectedCountry.phoneMax != null
    ) {
      const digits = form.phone.replace(/\D/g, "");
      if (
        digits &&
        (digits.length < selectedCountry.phoneMin ||
          digits.length > selectedCountry.phoneMax)
      ) {
        errors.phone = `${selectedCountry.name} phone numbers use ${selectedCountry.phoneMin}\u2013${selectedCountry.phoneMax} digits.`;
      }
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

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
    if (!employee && !validateHireFields()) {
      setFormError("Please fix the highlighted fields.");
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
          email: form.email.trim(),
          phone: form.phone.trim(),
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
    <Dialog
      open={open}
      onOpenChange={(next) => !saving && onOpenChange(next)}
    >
      <DialogContent className="sm:max-w-lg">
        <form
          onSubmit={(event) => void onSubmit(event)}
          onKeyDown={(event) => {
            // Enter must not implicitly submit the form from a mid-form input
            // (it fires createEmployee and slams the dialog shut); only the
            // footer buttons keep their Enter activation.
            if (event.key === "Enter" && (event.target as HTMLElement).tagName !== "BUTTON") {
              event.preventDefault();
            }
          }}
        >
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
              <Label htmlFor="first-name">
                First name <span className="text-destructive">*</span>
              </Label>
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
              <Label htmlFor="last-name">
                Last name <span className="text-destructive">*</span>
              </Label>
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
              <Label htmlFor="email">
                Email <span className="text-destructive">*</span>
              </Label>
              <Input
                id="email"
                type="email"
                value={form.email}
                aria-invalid={fieldErrors.email ? true : undefined}
                onChange={(event) => {
                  setForm((current) => ({ ...current, email: event.target.value }));
                  if (fieldErrors.email) {
                    setFieldErrors((current) => ({ ...current, email: undefined }));
                  }
                }}
              />
              {fieldErrors.email ? (
                <p className="text-xs font-medium text-destructive">{fieldErrors.email}</p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="phone">
                Phone <span className="text-destructive">*</span>
              </Label>
              <div className="flex gap-2">
                <CountryCombobox
                  kind="country"
                  id="phone-country"
                  className="w-32 shrink-0"
                  value={selectedCountryCode}
                  onChange={handlePhoneCountryChange}
                  placeholder="Country"
                  invalid={Boolean(fieldErrors.phone)}
                />
                <Input
                  id="phone"
                  className="flex-1"
                  inputMode="tel"
                  value={form.phone}
                  aria-invalid={fieldErrors.phone ? true : undefined}
                  onChange={(event) => {
                    setForm((current) => ({ ...current, phone: event.target.value }));
                    if (fieldErrors.phone) {
                      setFieldErrors((current) => ({ ...current, phone: undefined }));
                    }
                  }}
                />
              </div>
              {fieldErrors.phone ? (
                <p className="text-xs font-medium text-destructive">{fieldErrors.phone}</p>
              ) : selectedCountry?.phoneMin != null && selectedCountry.phoneMax != null ? (
                <p className="text-xs text-muted-foreground">
                  {selectedCountry.name}: {selectedCountry.phoneMin}
                  &ndash;
                  {selectedCountry.phoneMax} digits
                </p>
              ) : null}
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
              <div className="grid gap-3 sm:col-span-2 sm:grid-cols-[1fr_12rem]">
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
                  <CountryCombobox
                    kind="currency"
                    id="currency"
                    value={form.currency}
                    onChange={handleCurrencyChange}
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
