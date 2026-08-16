"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BadgeDollarSign, LoaderCircle, Plus } from "lucide-react";

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
import { listEmployees, type Employee } from "@/lib/api/hr-api";
import {
  createCompensationChange,
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
  const [record, setRecord] = useState({ effectiveFrom: "", monthlySalary: "", currency: "USD" });
  const [recordError, setRecordError] = useState<string | null>(null);
  const [recordSaving, setRecordSaving] = useState(false);

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
    setRecord({ effectiveFrom: "", monthlySalary: "", currency: "USD" });
    setRecordError(null);
    setRecordOpen(true);
  }

  async function onSubmitRecord(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (recordSaving || !canWrite) return;
    if (!selectedEmployeeId || !record.effectiveFrom || !record.monthlySalary.trim()) {
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
        employeeId: selectedEmployeeId,
        effectiveFrom: record.effectiveFrom,
        monthlySalary: record.monthlySalary.trim(),
        currency: record.currency.toUpperCase(),
      });
      setRecordOpen(false);
      setNotice({
        tone: "success",
        text: `Compensation change recorded (${formatDate(entry.effectiveFrom)}).`,
      });
      await loadHistory(selectedEmployeeId);
    } catch (error) {
      setRecordError(
        error instanceof ApiError ? error.message : "Could not record the change.",
      );
    } finally {
      setRecordSaving(false);
    }
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

      <Dialog open={recordOpen} onOpenChange={(open) => !recordSaving && setRecordOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={(event) => void onSubmitRecord(event)}>
            <DialogHeader>
              <DialogTitle>Record compensation change</DialogTitle>
              <DialogDescription>
                Set a new monthly salary for the selected employee. The current
                rate stops on the effective date.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
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
                      setRecord((current) => ({ ...current, monthlySalary: event.target.value }))
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
                onClick={() => setRecordOpen(false)}
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
    </div>
  );
}
