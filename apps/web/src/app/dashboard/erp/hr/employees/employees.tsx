"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Mail, Pencil, Plus, Search, UserRound, UserX } from "lucide-react";

import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
import {
  EmployeeFormDialog,
  TerminateEmployeeDialog,
} from "@/components/dashboard/erp/hr/employee-dialogs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  SearchableSelect,
  type SearchableSelectOption,
} from "@/components/dashboard/shared/searchable-select";
import { useModuleAccess } from "@/lib/access/modules";
import {
  listDepartments,
  listEmployees,
  type Department,
  type Employee,
  type EmployeeStatus,
} from "@/lib/api/hr-api";
import { createInvitation } from "@/lib/api/identity-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

export type EmployeeListView = "active" | "terminated";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; employees: Employee[]; totalPages: number };

type Notice = { tone: "success" | "error"; text: string };

/** "All statuses" on the active view excludes terminated employees -
 * they live in their own read-only list under the Terminated tab. */
const ACTIVE_STATUS_OPTIONS: { value: "all" | Exclude<EmployeeStatus, "terminated">; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "active", label: "Active" },
  { value: "on_leave", label: "On leave" },
];

const VIEW_TABS: { value: EmployeeListView; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "terminated", label: "Terminated" },
];

const PAGE_SIZE = 20;

export function EmployeesClient({ initialView = "active" }: { initialView?: EmployeeListView }) {
  const router = useRouter();
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.hr.write");

  const [view, setView] = useState<EmployeeListView>(initialView);
  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [departments, setDepartments] = useState<Department[]>([]);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | Exclude<EmployeeStatus, "terminated">>("all");
  const [departmentFilter, setDepartmentFilter] = useState<string>("all");
  const [notice, setNotice] = useState<Notice | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editingEmployee, setEditingEmployee] = useState<Employee | null>(null);
  const [terminatingEmployee, setTerminatingEmployee] = useState<Employee | null>(null);
  const [invitingEmployee, setInvitingEmployee] = useState<Employee | null>(null);
  const [inviteBusy, setInviteBusy] = useState(false);

  const [debouncedQuery, setDebouncedQuery] = useState("");

  const statusOptions = useMemo<SearchableSelectOption[]>(
    () =>
      ACTIVE_STATUS_OPTIONS.map((option) => ({
        value: option.value,
        label: option.label,
      })),
    [],
  );
  const departmentFilterOptions = useMemo<SearchableSelectOption[]>(
    () => [
      { value: "all", label: "All departments" },
      ...departments.map((department) => ({
        value: department.id,
        label: department.name,
      })),
    ],
    [departments],
  );

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
            status:
              view === "terminated"
                ? "terminated"
                : statusFilter === "all"
                  ? ["active", "on_leave"]
                  : statusFilter,
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
  }, [page, debouncedQuery, view, statusFilter, departmentFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  function switchView(next: EmployeeListView) {
    if (next === view) return;
    setView(next);
    setPage(1);
    setNotice(null);
    setInvitingEmployee(null);
    router.replace(
      next === "terminated"
        ? "/dashboard/erp/hr/employees?view=terminated"
        : "/dashboard/erp/hr/employees",
      { scroll: false },
    );
  }

  const departmentName = useMemo(() => {
    const byId = new Map(departments.map((department) => [department.id, department.name]));
    return (id: string | null | undefined) => (id ? (byId.get(id) ?? null) : null);
  }, [departments]);

  async function sendInvite(employee: Employee) {
    if (!employee.email || inviteBusy) return;
    setInviteBusy(true);
    try {
      await createInvitation(employee.email, "employee_self_service", {
        expiresInHours: 72,
      });
      setNotice({
        tone: "success",
        text: `Portal invite sent to ${employee.email}. The link expires in 72 hours.`,
      });
      setInvitingEmployee(null);
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError
            ? error.message
            : "Could not send the portal invite.",
      });
    } finally {
      setInviteBusy(false);
    }
  }

  const actionButtons = (employee: Employee) => {
    if (!canWrite || view !== "active") return null;
    const confirming = invitingEmployee?.id === employee.id;
    return (
      <div className="flex items-center justify-end gap-1">
        {confirming ? (
          <div
            className="flex items-center gap-2"
            onClick={(event) => event.stopPropagation()}
          >
            <span className="whitespace-nowrap text-xs text-muted-foreground">
              Send portal invite?
            </span>
            <Button
              type="button"
              size="sm"
              className="h-7 px-2.5 text-xs"
              disabled={inviteBusy}
              onClick={() => void sendInvite(employee)}
            >
              {inviteBusy ? "Sending…" : "Send"}
            </Button>
            <button
              type="button"
              onClick={() => setInvitingEmployee(null)}
              disabled={inviteBusy}
              aria-label="Cancel invite"
              className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline disabled:cursor-not-allowed disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        ) : (
          <>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                setInvitingEmployee(employee);
              }}
              disabled={!employee.email}
              aria-label={
                employee.email
                  ? `Send portal invite to ${employee.firstName} ${employee.lastName}`
                  : `${employee.firstName} ${employee.lastName} has no email on file`
              }
              title={
                employee.email
                  ? "Send leave-portal invite"
                  : "Add an email before sending a portal invite"
              }
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <Mail aria-hidden="true" className="size-3.5" />
            </button>
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
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                setTerminatingEmployee(employee);
              }}
              aria-label={`Terminate ${employee.firstName} ${employee.lastName}`}
              title="Terminate employee"
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
            >
              <UserX aria-hidden="true" className="size-3.5" />
            </button>
          </>
        )}
      </div>
    );
  };

  const columns: ErpColumn<Employee>[] =
    view === "active"
      ? [
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
                {departmentName(employee.departmentId) ?? "-"}
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
                  : "-"}
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
                  render: actionButtons,
                },
              ]
            : []),
        ]
      : [
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
                {departmentName(employee.departmentId) ?? "-"}
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
          {
            key: "terminationDate",
            label: "Terminated",
            render: (employee) => (
              <span className="text-muted-foreground">
                {employee.terminationDate ? formatDate(employee.terminationDate) : "-"}
              </span>
            ),
          },
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
          description={
            view === "terminated"
              ? "Former team members - a historical record of terminated employment."
              : "Everyone currently on the team - hire, edit, and manage employment."
          }
          icon={UserRound}
        />
        {canWrite && view === "active" ? (
          <Button type="button" onClick={openCreate}>
            <Plus aria-hidden="true" className="size-4" />
            New employee
          </Button>
        ) : null}
      </div>

      <nav
        aria-label="Employees views"
        role="tablist"
        className="flex items-center gap-1 overflow-x-auto border-b border-border/60"
        style={{ scrollbarWidth: "none" }}
      >
        {VIEW_TABS.map((tab) => {
          const active = tab.value === view;
          return (
            <button
              key={tab.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => switchView(tab.value)}
              className={cn(
                "relative inline-flex h-9 shrink-0 items-center px-3 text-sm font-medium transition-colors",
                active
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute bottom-0 left-3 right-3 h-[2px] rounded-full bg-emerald-500 dark:bg-emerald-400"
                />
              )}
            </button>
          );
        })}
      </nav>

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
        {view === "active" ? (
          <SearchableSelect
            className="w-40"
            options={statusOptions}
            value={statusFilter}
            onValueChange={(value) => {
              setStatusFilter(value as "all" | Exclude<EmployeeStatus, "terminated">);
              setPage(1);
            }}
            placeholder="Status"
          />
        ) : null}
        <SearchableSelect
          className="w-48"
          options={departmentFilterOptions}
          value={departmentFilter}
          onValueChange={(value) => {
            setDepartmentFilter(value);
            setPage(1);
          }}
          placeholder="Department"
        />
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

      {status.state === "loading" ? (
        <ErpDataTableSkeleton columns={view === "active" ? 7 : 5} />
      ) : null}

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
      <TerminateEmployeeDialog
        employee={terminatingEmployee}
        onOpenChange={(open) => {
          if (!open) setTerminatingEmployee(null);
        }}
        onSaved={(employee, text) => {
          setNotice({
            tone: "success",
            text: `${text} They now appear under the Terminated tab.`,
          });
          void load();
        }}
      />
    </div>
  );
}
