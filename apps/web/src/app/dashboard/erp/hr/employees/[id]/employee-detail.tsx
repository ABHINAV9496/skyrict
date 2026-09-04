"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  BadgeDollarSign,
  Building2,
  CalendarClock,
  CalendarDays,
  Leaf,
  Mail,
  Pencil,
  Phone,
  Trash2,
  UserCheck,
  UserRound,
} from "lucide-react";

import {
  ChangeStatusDialog,
  EmployeeFormDialog,
  TerminateEmployeeDialog,
} from "@/components/dashboard/erp/hr/employee-dialogs";
import { LogAttendanceDialog } from "@/components/dashboard/erp/hr/log-attendance-dialog";
import { LogLeaveDialog } from "@/components/dashboard/erp/hr/log-leave-dialog";
import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
import { Button } from "@/components/ui/button";
import { useModuleAccess } from "@/lib/access/modules";
import {
  getEmployee,
  getLeaveBalances,
  listAttendance,
  listDepartments,
  listEmployees,
  listLeaveMovements,
  type AttendanceRecord,
  type Department,
  type Employee,
  type LeaveBalance,
  type LeaveMovement,
} from "@/lib/api/hr-api";
import { listCompensation, type Compensation } from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready" };

type Notice = { tone: "success" | "error"; text: string };

function DetailItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-sm font-medium text-foreground">{value}</span>
    </div>
  );
}

function Card({
  title,
  icon: Icon,
  actions,
  children,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-sm font-semibold tracking-tight text-foreground">
          <Icon aria-hidden="true" className="size-4 text-primary" />
          {title}
        </h2>
        {actions}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function EmployeeDetailClient({ employeeId }: { employeeId: string }) {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.hr.write");
  const canReadPayroll =
    permissions.includes("*") || permissions.includes("erp.payroll.read");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [movements, setMovements] = useState<LeaveMovement[]>([]);
  const [attendance, setAttendance] = useState<AttendanceRecord[]>([]);
  const [compensation, setCompensation] = useState<Compensation[] | null>(null);
  const [compensationError, setCompensationError] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [attendanceLogOpen, setAttendanceLogOpen] = useState(false);
  const [allEmployees, setAllEmployees] = useState<Employee[]>([]);
  const [terminating, setTerminating] = useState(false);
  const [statusTarget, setStatusTarget] = useState<"active" | "on_leave" | null>(null);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const results = await Promise.all([
        getEmployee(employeeId),
        listDepartments(),
        getLeaveBalances(employeeId),
        listLeaveMovements(employeeId),
        listAttendance({ pageSize: 10, filters: { employeeId } }),
      ]);
      setEmployee(results[0]);
      setDepartments(results[1]);
      setBalances(results[2]);
      setMovements(results[3]);
      setAttendance(results[4].items);
      setStatus({ state: "ready" });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load this employee.";
      setStatus({ state: "error", message });
    }
  }, [employeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!canReadPayroll) {
      setCompensation(null);
      return;
    }
    let cancelled = false;
    void listCompensation(employeeId)
      .then((items) => {
        if (!cancelled) {
          setCompensation(items);
          setCompensationError(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCompensation(null);
          setCompensationError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [employeeId, canReadPayroll]);

  const departmentName = useMemo(() => {
    const byId = new Map(departments.map((department) => [department.id, department.name]));
    return (id: string | null | undefined) => (id ? (byId.get(id) ?? null) : null);
  }, [departments]);

  function onSaved(updated: Employee, text: string) {
    setEmployee(updated);
    setNotice({ tone: "success", text });
    void load();
  }

  async function openLogLeave() {
    if (allEmployees.length === 0) {
      try {
        const result = await listEmployees({ pageSize: 100 });
        setAllEmployees(result.items);
      } catch {
        setAllEmployees([]);
      }
    }
    setLogOpen(true);
  }

  async function openLogAttendance() {
    if (allEmployees.length === 0) {
      try {
        const result = await listEmployees({ pageSize: 100 });
        setAllEmployees(result.items);
      } catch {
        setAllEmployees([]);
      }
    }
    setAttendanceLogOpen(true);
  }

  if (status.state === "loading") {
    return <ErpDataTableSkeleton columns={4} />;
  }

  if (status.state === "error" || !employee) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-12 text-center">
        <p className="text-sm font-medium text-destructive">
          {status.state === "error" ? status.message : "Employee not found."}
        </p>
        <Button asChild variant="outline" size="sm" className="mt-3">
          <Link href="/dashboard/erp/hr/employees">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Back to employees
          </Link>
        </Button>
      </div>
    );
  }

  const movementColumns: ErpColumn<LeaveMovement>[] = [
    {
      key: "leaveType",
      label: "Type",
      render: (movement) => (
        <span className="font-medium text-foreground">{movement.leaveType}</span>
      ),
    },
    {
      key: "qty",
      label: "Days",
      align: "right",
      render: (movement) => (
        <span className="tabular-nums text-muted-foreground">
          {movement.qty > 0 ? `+${movement.qty}` : movement.qty}
        </span>
      ),
    },
    {
      key: "refType",
      label: "Source",
      render: (movement) => (
        <span className="text-muted-foreground">
          {movement.refType || "Manual"}
        </span>
      ),
    },
    {
      key: "occurredAt",
      label: "Date",
      render: (movement) => (
        <span className="text-muted-foreground">
          {movement.occurredAt ? formatDateTime(movement.occurredAt) : "-"}
        </span>
      ),
    },
  ];

  const attendanceColumns: ErpColumn<AttendanceRecord>[] = [
    {
      key: "workDate",
      label: "Date",
      render: (record) => (
        <span className="font-medium text-foreground">{formatDate(record.workDate)}</span>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (record) => <StatusBadge status={record.status} />,
    },
    {
      key: "payImpact",
      label: "Pay impact",
      render: (record) => (
        <span className="text-muted-foreground">
          {record.payImpact === "full"
            ? "Full day"
            : record.payImpact === "half"
              ? "Half day"
              : "No pay"}
        </span>
      ),
    },
    {
      key: "note",
      label: "Note",
      render: (record) => (
        <span className="text-muted-foreground">{record.note ?? "-"}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <Button asChild variant="ghost" size="sm" className="-ml-2 text-muted-foreground">
          <Link href="/dashboard/erp/hr/employees">
            <ArrowLeft aria-hidden="true" className="size-4" />
            Employees
          </Link>
        </Button>
        {canWrite ? (
          <div className="flex items-center gap-2">
            {employee.employmentStatus === "active" ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setStatusTarget("on_leave")}
              >
                <Leaf aria-hidden="true" className="size-4" />
                Place on leave
              </Button>
            ) : null}
            {employee.employmentStatus === "on_leave" ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setStatusTarget("active")}
              >
                <UserCheck aria-hidden="true" className="size-4" />
                Reactivate
              </Button>
            ) : null}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setFormOpen(true)}
            >
              <Pencil aria-hidden="true" className="size-4" />
              Edit
            </Button>
            {employee.employmentStatus !== "terminated" ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => setTerminating(true)}
              >
                <Trash2 aria-hidden="true" className="size-4" />
                Terminate
              </Button>
            ) : null}
          </div>
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

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-4">
          <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <UserRound aria-hidden="true" className="size-6" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-display text-xl font-semibold tracking-tight text-foreground">
                {employee.firstName} {employee.lastName}
              </h1>
              <StatusBadge status={employee.employmentStatus} />
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {employee.jobTitle}
              {departmentName(employee.departmentId)
                ? ` · ${departmentName(employee.departmentId)}`
                : ""}
              {" · "}
              {employee.employeeNumber}
            </p>
            {employee.activeCompensation ? (
              <p className="mt-1 text-sm font-medium text-primary">
                {formatMoney(
                  employee.activeCompensation.amount,
                  employee.activeCompensation.currency,
                )}
                <span className="font-normal text-muted-foreground"> / month</span>
              </p>
            ) : null}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Profile" icon={UserRound}>
          <div className="divide-y divide-border">
            <DetailItem label="Employee number" value={employee.employeeNumber} />
            <DetailItem label="Department" value={departmentName(employee.departmentId) ?? "-"} />
            <DetailItem label="Hired" value={formatDate(employee.hireDate)} />
            {employee.terminationDate ? (
              <DetailItem label="Terminated" value={formatDate(employee.terminationDate)} />
            ) : null}
            <DetailItem
              label="Email"
              value={
                employee.email ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Mail aria-hidden="true" className="size-3.5 text-muted-foreground" />
                    {employee.email}
                  </span>
                ) : (
                  "-"
                )
              }
            />
            <DetailItem
              label="Phone"
              value={
                employee.phone ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Phone aria-hidden="true" className="size-3.5 text-muted-foreground" />
                    {employee.phone}
                  </span>
                ) : (
                  "-"
                )
              }
            />
          </div>
        </Card>

        <Card
          title="Leave balances"
          icon={CalendarDays}
          actions={
            canWrite ? (
              <Button type="button" variant="outline" size="sm" onClick={() => void openLogLeave()}>
                Log leave
              </Button>
            ) : undefined
          }
        >
          {balances.length === 0 ? (
            <p className="text-sm text-muted-foreground">No leave balances yet.</p>
          ) : (
            <div className="divide-y divide-border">
              {balances.map((balance) => (
                <DetailItem
                  key={`${balance.employeeId}-${balance.leaveType}`}
                  label={balance.leaveType}
                  value={`${balance.balance} days`}
                />
              ))}
            </div>
          )}
        </Card>
      </div>

      {canReadPayroll ? (
        <Card title="Compensation history" icon={BadgeDollarSign}>
          {compensationError ? (
            <p className="text-sm text-muted-foreground">
              Compensation history couldn&apos;t be loaded. Check your connection
              and try again.
            </p>
          ) : compensation === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : compensation.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No compensation changes on record.
            </p>
          ) : (
            <div className="divide-y divide-border">
              {compensation.map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center justify-between gap-4 py-2"
                >
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      {formatMoney(entry.monthlySalary.amount, entry.monthlySalary.currency)}
                      <span className="font-normal text-muted-foreground"> / month</span>
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Effective {formatDate(entry.effectiveFrom)}
                    </p>
                  </div>
                  <StatusBadge status={entry.isActive ? "active" : "cancelled"} />
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-4">
          <Building2 aria-hidden="true" className="size-5 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Compensation history is part of Payroll. It&apos;ll appear here once
            your role includes{" "}
            <span className="font-medium text-foreground">erp.payroll.read</span>.
          </p>
        </div>
      )}

      <Card title="Leave movements" icon={CalendarDays}>
        {movements.length === 0 ? (
          <p className="text-sm text-muted-foreground">No leave movements yet.</p>
        ) : (
          <ErpDataTable
            columns={movementColumns}
            rows={movements}
            meta={{ total: movements.length, page: 1, page_size: movements.length, total_pages: 1 }}
          />
        )}
      </Card>

      <Card
        title="Attendance"
        icon={CalendarClock}
        actions={
          canWrite ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void openLogAttendance()}
            >
              Log attendance
            </Button>
          ) : undefined
        }
      >
        {attendance.length === 0 ? (
          <p className="text-sm text-muted-foreground">No attendance records yet.</p>
        ) : (
          <>
            <ErpDataTable
              columns={attendanceColumns}
              rows={attendance}
              meta={{
                total: attendance.length,
                page: 1,
                page_size: attendance.length,
                total_pages: 1,
              }}
            />
            <div className="mt-3">
              <Link
                href={`/dashboard/erp/hr/attendance?employee=${employeeId}`}
                className="text-sm font-medium text-primary hover:underline"
              >
                View all attendance →
              </Link>
            </div>
          </>
        )}
      </Card>

      <EmployeeFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        departments={departments}
        employee={employee}
        onSaved={onSaved}
      />

      <TerminateEmployeeDialog
        employee={terminating ? employee : null}
        onOpenChange={(open) => !open && setTerminating(false)}
        onSaved={onSaved}
      />

      <ChangeStatusDialog
        employee={statusTarget ? employee : null}
        target={statusTarget}
        onOpenChange={(open) => !open && setStatusTarget(null)}
        onSaved={onSaved}
      />

      <LogLeaveDialog
        open={logOpen}
        onOpenChange={setLogOpen}
        employees={allEmployees}
        prefillEmployeeId={employeeId}
        onCreated={() => void load()}
      />

      <LogAttendanceDialog
        open={attendanceLogOpen}
        onOpenChange={setAttendanceLogOpen}
        employees={allEmployees}
        prefillEmployeeId={employeeId}
        onSaved={() => void load()}
      />
    </div>
  );
}
