"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Pencil, Plus, Search, UserRound } from "lucide-react";

import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
import {
  EmployeeFormDialog,
} from "@/components/dashboard/erp/hr/employee-dialogs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useModuleAccess } from "@/lib/access/modules";
import {
  listDepartments,
  listEmployees,
  type Department,
  type Employee,
  type EmployeeStatus,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; employees: Employee[]; totalPages: number };

type Notice = { tone: "success" | "error"; text: string };

const STATUS_OPTIONS: { value: "all" | EmployeeStatus; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "on_leave", label: "On leave" },
  { value: "terminated", label: "Terminated" },
];

const PAGE_SIZE = 20;

export function EmployeesClient() {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.hr.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [departments, setDepartments] = useState<Department[]>([]);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | EmployeeStatus>("all");
  const [departmentFilter, setDepartmentFilter] = useState<string>("all");
  const [notice, setNotice] = useState<Notice | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null);

  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [employeesResult, departmentList] = await Promise.all([
        listEmployees({
          page,
          pageSize: PAGE_SIZE,
          filters: {
            q: debouncedQuery || undefined,
            status: statusFilter === "all" ? undefined : statusFilter,
            departmentId:
              departmentFilter === "all" ? undefined : departmentFilter,
          },
        }),
        listDepartments(),
      ]);
      setDepartments(departmentList);
      setStatus({
        state: "ready",
        employees: employeesResult.items,
        totalPages: employeesResult.meta.total_pages,
      });
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Could not load employees.";
      setStatus({ state: "error", message });
    }
  }, [page, debouncedQuery, statusFilter, departmentFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const departmentName = useMemo(() => {
    const byId = new Map(departments.map((department) => [department.id, department.name]));
    return (id: string | null | undefined) => (id ? (byId.get(id) ?? null) : null);
  }, [departments]);

  const columns: ErpColumn<Employee>[] = [
    {
      key: "lastName",
      label: "Employee",
      render: (employee) => (
        <div>
          <p className="font-medium text-foreground">
            {employee.firstName} {employee.lastName}
          </p>
          <p className="text-xs text-muted-foreground">{employee.employeeNumber}</p>
        </div>
      ),
    },
    {
      key: "jobTitle",
      label: "Role",
      render: (employee) => (
        <span className="text-muted-foreground">{employee.jobTitle}</span>
      ),
    },
    {
      key: "departmentId",
      label: "Department",
      render: (employee) => (
        <span className="text-muted-foreground">
          {departmentName(employee.departmentId) ?? "—"}
        </span>
      ),
    },
    {
      key: "employmentStatus",
      label: "Status",
      render: (employee) => <StatusBadge status={employee.employmentStatus} />,
    },
    {
      key: "activeCompensation",
      label: "Compensation",
      align: "right",
      render: (employee) => (
        <span className="tabular-nums text-muted-foreground">
          {employee.activeCompensation
            ? formatMoney(
                employee.activeCompensation.amount,
                employee.activeCompensation.currency,
              )
            : "—"}
        </span>
      ),
    },
    {
      key: "hireDate",
      label: "Hired",
      render: (employee) => (
        <span className="text-muted-foreground">{formatDate(employee.hireDate)}</span>
      ),
    },
    ...(canWrite
      ? [
          {
            key: "id" as const,
            label: "",
            align: "right" as const,
            render: (employee: Employee) => (
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  setEditingEmployee(employee);
                  setFormOpen(true);
                }}
                aria-label={`Edit ${employee.firstName} ${employee.lastName}`}
                title="Edit employee"
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
    setEditingEmployee(null);
    setFormOpen(true);
  }

  function onSaved(_employee: Employee, text: string) {
    setNotice({ tone: "success", text });
    void load();
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Employees"
          description="Everyone on the team — hire, edit, and manage employment status."
          icon={UserRound}
        />
        {canWrite ? (
          <Button type="button" onClick={openCreate}>
            <Plus aria-hidden="true" className="size-4" />
            New employee
          </Button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-64">
          <Search
            aria-hidden="true"
            className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
            className="pl-8"
            placeholder="Search by name"
            aria-label="Search employees"
          />
        </div>
        <Select
          value={statusFilter}
          onValueChange={(value) => {
            setStatusFilter(value as "all" | EmployeeStatus);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-40" aria-label="Filter by status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={departmentFilter}
          onValueChange={(value) => {
            setDepartmentFilter(value);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-48" aria-label="Filter by department">
            <SelectValue placeholder="Department" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All departments</SelectItem>
            {departments.map((department) => (
              <SelectItem key={department.id} value={department.id}>
                {department.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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

      {status.state === "loading" ? <ErpDataTableSkeleton columns={7} /> : null}

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
          rows={status.employees}
          meta={{
            total: status.employees.length,
            page,
            page_size: PAGE_SIZE,
            total_pages: status.totalPages,
          }}
          onPageChange={setPage}
          onRowClick={(employee) =>
            router.push(`/dashboard/erp/hr/employees/${employee.id}`)
          }
        />
      ) : null}

      <EmployeeFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        departments={departments}
        employee={editingEmployee}
        onSaved={onSaved}
      />
    </div>
  );
}
