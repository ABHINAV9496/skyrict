"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Building2, LoaderCircle, Pencil, Plus } from "lucide-react";

import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
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
import { useModuleAccess } from "@/lib/access/modules";
import {
  createDepartment,
  listDepartments,
  listEmployees,
  updateDepartment,
  type Department,
  type Employee,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; departments: Department[] };

type Notice = { tone: "success" | "error"; text: string };

interface DepartmentFormState {
  name: string;
  managerEmployeeId: string;
}

const EMPTY_FORM: DepartmentFormState = { name: "", managerEmployeeId: "" };

export function DepartmentsClient() {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.hr.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Department | null>(null);
  const [form, setForm] = useState<DepartmentFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [departmentList, employeeList] = await Promise.all([
        listDepartments(),
        listEmployees({ pageSize: 50 }),
      ]);
      setEmployees(employeeList.items);
      setStatus({ state: "ready", departments: departmentList });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load departments.";
      setStatus({ state: "error", message });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const employeeName = useMemo(() => {
    const byId = new Map(employees.map((employee) => [employee.id, `${employee.firstName} ${employee.lastName}`]));
    return (id: string | null | undefined) => (id ? (byId.get(id) ?? null) : null);
  }, [employees]);

  const columns: ErpColumn<Department>[] = [
    {
      key: "name",
      label: "Department",
      render: (department) => (
        <p className="font-medium text-foreground">{department.name}</p>
      ),
    },
    {
      key: "managerEmployeeId",
      label: "Manager",
      render: (department) => (
        <span className="text-muted-foreground">
          {employeeName(department.managerEmployeeId) ?? "—"}
        </span>
      ),
    },
    {
      key: "isActive",
      label: "Status",
      render: (department) => (
        <StatusBadge status={department.isActive ? "active" : "cancelled"} />
      ),
    },
    ...(canWrite
      ? [
          {
            key: "id" as const,
            label: "",
            align: "right" as const,
            render: (department: Department) => (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  openEdit(department);
                }}
                aria-label={`Edit ${department.name}`}
                title="Edit department"
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Pencil aria-hidden="true" className="size-3.5" />
              </button>
            ),
          },
        ]
      : []),
  ];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setFormOpen(true);
  }

  function openEdit(department: Department) {
    setEditing(department);
    setForm({
      name: department.name,
      managerEmployeeId: department.managerEmployeeId ?? "",
    });
    setFormError(null);
    setFormOpen(true);
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !canWrite) return;
    if (!form.name.trim()) {
      setFormError("A department name is required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editing) {
        await updateDepartment(editing.id, {
          name: form.name.trim(),
          managerEmployeeId: form.managerEmployeeId || undefined,
        });
      } else {
        await createDepartment({
          name: form.name.trim(),
          managerEmployeeId: form.managerEmployeeId || undefined,
        });
      }
      setFormOpen(false);
      setNotice({
        tone: "success",
        text: editing
          ? `${form.name.trim()} updated.`
          : `${form.name.trim()} created.`,
      });
      await load();
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not save the department.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Departments"
          description="Team structure and the people who lead each group."
          icon={Building2}
        />
        {canWrite ? (
          <Button type="button" onClick={openCreate}>
            <Plus aria-hidden="true" className="size-4" />
            New department
          </Button>
        ) : null}
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

      {status.state === "loading" ? <ErpDataTableSkeleton columns={3} /> : null}

      {status.state === "error" ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
          <p className="text-sm font-medium text-destructive">{status.message}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => void load()}
          >
            Try again
          </Button>
        </div>
      ) : null}

      {status.state === "ready" ? (
        <ErpDataTable
          columns={columns}
          rows={status.departments}
          meta={{
            total: status.departments.length,
            page: 1,
            page_size: status.departments.length,
            total_pages: 1,
          }}
        />
      ) : null}

      <Dialog open={formOpen} onOpenChange={(open) => !saving && setFormOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={(event) => void onSubmit(event)}>
            <DialogHeader>
              <DialogTitle>
                {editing ? "Edit department" : "New department"}
              </DialogTitle>
              <DialogDescription>
                {editing
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
                onClick={() => setFormOpen(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : null}
                {editing ? "Save changes" : "Create department"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
