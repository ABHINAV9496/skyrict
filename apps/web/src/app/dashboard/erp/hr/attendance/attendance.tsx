"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock } from "lucide-react";

import { LogAttendanceDialog } from "@/components/dashboard/erp/hr/log-attendance-dialog";
import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
import { SearchableSelect } from "@/components/dashboard/shared/searchable-select";
import { Button } from "@/components/ui/button";
import { DatePicker } from "@/components/ui/date-picker";
import { useModuleAccess } from "@/lib/access/modules";
import {
  listAttendance,
  listEmployees,
  type AttendanceRecord,
  type AttendanceStatus,
  type Employee,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDate } from "@/lib/format";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; records: AttendanceRecord[]; totalPages: number };

const STATUS_FILTER_OPTIONS: { value: "all" | AttendanceStatus; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "on_time", label: "On time" },
  { value: "late", label: "Late" },
  { value: "absent", label: "Absent" },
];

const PAGE_SIZE = 20;

export function AttendanceClient({
  initialEmployeeId,
}: {
  initialEmployeeId?: string | null;
}) {
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.hr.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<"all" | AttendanceStatus>("all");
  const [employeeFilter, setEmployeeFilter] = useState<string>(initialEmployeeId ?? "all");
  const [dateFrom, setDateFrom] = useState<string | null>(null);
  const [dateTo, setDateTo] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(false);

  const employeeOptions = useMemo(
    () =>
      [...employees]
        .map((employee) => ({
          value: employee.id,
          label: `${employee.firstName} ${employee.lastName}`,
          keywords: employee.employeeNumber,
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [employees],
  );

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [attendanceResult, employeeList] = await Promise.all([
        listAttendance({
          page,
          pageSize: PAGE_SIZE,
          filters: {
            status: statusFilter === "all" ? undefined : statusFilter,
            employeeId: employeeFilter === "all" ? undefined : employeeFilter,
            dateFrom: dateFrom ?? undefined,
            dateTo: dateTo ?? undefined,
          },
        }),
        listEmployees({ pageSize: 100 }),
      ]);
      setEmployees(employeeList.items);
      setStatus({
        state: "ready",
        records: attendanceResult.items,
        totalPages: attendanceResult.meta.total_pages,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load attendance.";
      setStatus({ state: "error", message });
    }
  }, [page, statusFilter, employeeFilter, dateFrom, dateTo]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ErpColumn<AttendanceRecord>[] = [
    {
      key: "firstName",
      label: "Employee",
      render: (record) => (
        <span className="font-medium text-foreground">
          {record.firstName && record.lastName
            ? `${record.firstName} ${record.lastName}`
            : record.employeeId}
        </span>
      ),
    },
    {
      key: "workDate",
      label: "Date",
      render: (record) => (
        <span className="text-muted-foreground">{formatDate(record.workDate)}</span>
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
        <span className="text-muted-foreground">{record.note ?? "—"}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance"
        description="Daily attendance per employee — late arrivals pay half, absences none."
        icon={CalendarClock}
      />

      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            Records
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <SearchableSelect
              options={[{ value: "all", label: "All employees" }, ...employeeOptions]}
              value={employeeFilter}
              onValueChange={(value) => {
                setEmployeeFilter(value);
                setPage(1);
              }}
              placeholder="All employees"
              className="w-48"
            />
            <SearchableSelect
              options={STATUS_FILTER_OPTIONS}
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value as "all" | AttendanceStatus);
                setPage(1);
              }}
              placeholder="Status"
              className="w-40"
            />
            <DatePicker
              value={dateFrom}
              onChange={(iso) => {
                setDateFrom(iso ?? null);
                setPage(1);
              }}
              placeholder="From date"
              className="w-36"
            />
            <DatePicker
              value={dateTo}
              onChange={(iso) => {
                setDateTo(iso ?? null);
                setPage(1);
              }}
              placeholder="To date"
              className="w-36"
            />
            {canWrite ? (
              <Button type="button" variant="outline" size="sm" onClick={() => setLogOpen(true)}>
                Log attendance
              </Button>
            ) : null}
          </div>
        </div>

        <div className="mt-4">
          {status.state === "loading" ? <ErpDataTableSkeleton columns={5} /> : null}
          {status.state === "error" ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-border px-4 py-10 text-center">
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
              rows={status.records}
              meta={{
                total: status.records.length,
                page,
                page_size: PAGE_SIZE,
                total_pages: status.totalPages,
              }}
              onPageChange={setPage}
            />
          ) : null}
        </div>
      </section>

      <LogAttendanceDialog
        open={logOpen}
        onOpenChange={setLogOpen}
        employees={employees}
        prefillEmployeeId={employeeFilter === "all" ? null : employeeFilter}
        onSaved={() => void load()}
      />
    </div>
  );
}
