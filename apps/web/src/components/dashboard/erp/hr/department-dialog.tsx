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
import {
  createDepartment,
  updateDepartment,
  type Department,
  type Employee,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";

interface DepartmentFormState {
  name: string;
  managerEmployeeId: string;
}

const EMPTY_FORM: DepartmentFormState = { name: "", managerEmployeeId: "" };

/** Create/edit a department. Pass `department: null` to create. */
export function DepartmentDialog({
  open,
  onOpenChange,
  employees,
  department,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  employees: Employee[];
  department: Department | null;
  onSaved: (message: string) => void;
}) {
  const [form, setForm] = useState<DepartmentFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(
      department
        ? {
            name: department.name,
            managerEmployeeId: department.managerEmployeeId ?? "",
          }
        : EMPTY_FORM,
    );
    setFormError(null);
  }, [open, department]);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (!form.name.trim()) {
      setFormError("A department name is required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (department) {
        await updateDepartment(department.id, {
          name: form.name.trim(),
          managerEmployeeId: form.managerEmployeeId || undefined,
        });
      } else {
        await createDepartment({
          name: form.name.trim(),
          managerEmployeeId: form.managerEmployeeId || undefined,
        });
      }
      onOpenChange(false);
      onSaved(
        department ? `${form.name.trim()} updated.` : `${form.name.trim()} created.`,
      );
    } catch (error) {
      setFormError(
        error instanceof ApiError ? error.message : "Could not save the department.",
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
            <DialogTitle>
              {department ? "Edit department" : "New department"}
            </DialogTitle>
            <DialogDescription>
              {department
                ? "Update the department's name or manager."
                : "Create a department and optionally assign a manager."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="space-y-1.5">
              <Label htmlFor="department-name">Name</Label>
              <Input
                id="department-name"
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
                placeholder="e.g. Engineering"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="department-manager">Manager (optional)</Label>
              <Select
                value={form.managerEmployeeId}
                onValueChange={(value) =>
                  setForm((current) => ({
                    ...current,
                    managerEmployeeId: value === "none" ? "" : value,
                  }))
                }
              >
                <SelectTrigger id="department-manager" className="w-full">
                  <SelectValue placeholder="No manager" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No manager</SelectItem>
                  {employees.map((employee) => (
                    <SelectItem key={employee.id} value={employee.id}>
                      {employee.firstName} {employee.lastName}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
              {department ? "Save changes" : "Create department"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
