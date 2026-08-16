"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BadgeDollarSign, Plus } from "lucide-react";

import { CompensationDialog } from "@/components/dashboard/erp/payroll/compensation-dialog";
import { ErpDataTable, ErpDataTableSkeleton, type ErpColumn } from "@/components/dashboard/shared/erp-data-table";
import { PageHeader } from "@/components/dashboard/shared/page-header";
import { StatusBadge } from "@/components/dashboard/shared/status-badge";
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
import { listEmployees, type Employee } from "@/lib/api/hr-api";
import {
  listCompensation,
  type Compensation,
} from "@/lib/api/payroll-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready" };

type Notice = { tone: "success" | "error"; text: string };

export function CompensationClient() {
  const { permissions } = useModuleAccess();
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.payroll.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [directoryUnavailable, setDirectoryUnavailable] = useState(false);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string>("");
  const [manualEmployeeId, setManualEmployeeId] = useState("");
  const [history, setHistory] = useState<Compensation[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);

  const [recordOpen, setRecordOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      setEmployees(await listEmployees({ pageSize: 100 }).then((result) => result.items));
      setDirectoryUnavailable(false);
    } catch {
      setDirectoryUnavailable(true);
      setEmployees([]);
    } finally {
      setStatus({ state: "ready" });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedEmployee = useMemo(
    () => employees.find((employee) => employee.id === selectedEmployeeId) ?? null,
    [employees, selectedEmployeeId],
  );

  const loadHistory = useCallback(
    async (employeeId: string) => {
      setHistoryLoading(true);
      setHistoryError(null);
      try {
        setHistory(await listCompensation(employeeId));
      } catch (error) {
        setHistory([]);
        setHistoryError(
          error instanceof ApiError ? error.message : "Could not load compensation history.",
        );
      } finally {
        setHistoryLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (selectedEmployeeId) {
      void loadHistory(selectedEmployeeId);
    } else {
      setHistory([]);
    }
  }, [selectedEmployeeId, loadHistory]);

  function openRecord() {
    setRecordOpen(true);
  }

  const columns: ErpColumn<Compensation>[] = [
    {
      key: "effectiveFrom",
      label: "Effective",
      render: (entry) => (
        <span className="text-muted-foreground">{formatDate(entry.effectiveFrom)}</span>
      ),
    },
    {
      key: "monthlySalary",
      label: "Monthly salary",
      align: "right",
      render: (entry) => (
        <span className="tabular-nums font-medium text-foreground">
          {formatMoney(entry.monthlySalary.amount, entry.monthlySalary.currency)}
        </span>
      ),
    },
    {
      key: "isActive",
      label: "Status",
      render: (entry) => (
        <StatusBadge status={entry.isActive ? "active" : "cancelled"} />
      ),
    },
    {
      key: "createdAt",
      label: "Recorded",
      render: (entry) => (
        <span className="text-muted-foreground">{formatDate(entry.createdAt)}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Compensation"
          description="Salary history and the current rate for every employee."
          icon={BadgeDollarSign}
        />
        {canWrite ? (
          <Button type="button" onClick={openRecord} disabled={!selectedEmployeeId} title={selectedEmployeeId ? undefined : "Choose an employee first"}>
            <Plus aria-hidden="true" className="size-4" />
            Record change
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

      {status.state === "loading" ? <ErpDataTableSkeleton columns={4} /> : null}

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
        <>
          <section className="rounded-xl border border-border bg-card p-5">
            <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
              Employee
            </h2>
            <div className="mt-3">
              {directoryUnavailable ? (
                <div className="space-y-3">
                  <p className="text-sm text-muted-foreground">
                    The employee directory isn&apos;t available to your role. Enter
                    an employee ID to continue.
                  </p>
                  <Input
                    value={manualEmployeeId}
                    onChange={(event) => {
                      setManualEmployeeId(event.target.value);
                      setSelectedEmployeeId(event.target.value.trim());
                    }}
                    placeholder="Employee ID"
                    aria-label="Employee ID"
                    className="max-w-sm"
                  />
                </div>
              ) : (
                <Select
                  value={selectedEmployeeId}
                  onValueChange={setSelectedEmployeeId}
                >
                  <SelectTrigger className="w-full max-w-sm" aria-label="Select employee">
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
              )}
              {selectedEmployee ? (
                <p className="mt-3 text-sm text-muted-foreground">
                  {selectedEmployee.jobTitle}
                  {selectedEmployee.activeCompensation
                    ? ` · currently ${formatMoney(
                        selectedEmployee.activeCompensation.amount,
                        selectedEmployee.activeCompensation.currency,
                      )}/month`
                    : ""}
                </p>
              ) : null}
            </div>
          </section>

          <section className="rounded-xl border border-border bg-card p-5">
            <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
              History
            </h2>
            <div className="mt-4">
              {!selectedEmployeeId ? (
                <p className="text-sm text-muted-foreground">
                  Choose an employee to see their compensation history.
                </p>
              ) : historyLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : historyError ? (
                <p className="text-sm font-medium text-destructive">{historyError}</p>
              ) : history.length === 0 ? (
                <p className="text-sm text-muted-foreground">No changes on record.</p>
              ) : (
                <ErpDataTable
                  columns={columns}
                  rows={history}
                  meta={{ total: history.length, page: 1, page_size: history.length, total_pages: 1 }}
                />
              )}
            </div>
          </section>
        </>
      ) : null}

      <CompensationDialog
        open={recordOpen}
        onOpenChange={setRecordOpen}
        employees={employees}
        defaultEmployeeId={selectedEmployeeId}
        onSaved={(message) => {
          setNotice({ tone: "success", text: message });
          if (selectedEmployeeId) {
            void loadHistory(selectedEmployeeId);
          }
        }}
      />
    </div>
  );
}
