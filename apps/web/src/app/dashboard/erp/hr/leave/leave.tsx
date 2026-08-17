"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarDays, Check, LoaderCircle, X } from "lucide-react";

import { LogLeaveDialog } from "@/components/dashboard/erp/hr/log-leave-dialog";
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
  accrueLeave,
  adjustLeaveBalance,
  approveLeaveRequest,
  cancelLeaveRequest,
  getLeaveBalances,
  listEmployees,
  listLeaveRequests,
  rejectLeaveRequest,
  type Employee,
  type LeaveBalance,
  type LeaveRequest,
  type LeaveRequestStatus,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; requests: LeaveRequest[]; totalPages: number };

type Notice = { tone: "success" | "error"; text: string };

const STATUS_OPTIONS: { value: "all" | LeaveRequestStatus; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "cancelled", label: "Cancelled" },
];

const PAGE_SIZE = 20;

export function LeaveClient({ initialStatus }: { initialStatus?: LeaveRequestStatus }) {
  const { permissions } = useModuleAccess();
  const canApprove =
    permissions.includes("*") || permissions.includes("erp.hr.approve");
  const canWrite =
    permissions.includes("*") || permissions.includes("erp.hr.write");
  const canAct =
    canWrite || canApprove;

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<"all" | LeaveRequestStatus>(initialStatus ?? "all");
  const [employeeFilter, setEmployeeFilter] = useState<string>("all");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null);
  const [balances, setBalances] = useState<LeaveBalance[]>([]);
  const [balancesLoading, setBalancesLoading] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustError, setAdjustError] = useState<string | null>(null);
  const [adjustSaving, setAdjustSaving] = useState(false);
  const [adjust, setAdjust] = useState({ leaveType: "", qty: "", reason: "" });
  const [accruing, setAccruing] = useState(false);
  const [logOpen, setLogOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [requestsResult, employeeList] = await Promise.all([
        listLeaveRequests({
          page,
          pageSize: PAGE_SIZE,
          filters: {
            status: statusFilter === "all" ? undefined : statusFilter,
            employeeId: employeeFilter === "all" ? undefined : employeeFilter,
          },
        }),
        listEmployees({ pageSize: 100 }),
      ]);
      setEmployees(employeeList.items);
      setStatus({
        state: "ready",
        requests: requestsResult.items,
        totalPages: requestsResult.meta.total_pages,
      });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load leave requests.";
      setStatus({ state: "error", message });
    }
  }, [page, statusFilter, employeeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const employeeName = useMemo(() => {
    const byId = new Map(employees.map((employee) => [employee.id, `${employee.firstName} ${employee.lastName}`]));
    return (id: string) => byId.get(id) ?? null;
  }, [employees]);

  async function loadBalances(employeeId: string) {
    setBalancesLoading(true);
    try {
      setBalances(await getLeaveBalances(employeeId));
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not load balances.",
      });
      setBalances([]);
    } finally {
      setBalancesLoading(false);
    }
  }

  const loadBalancesCallback = useCallback(
    (employeeId: string) => void loadBalances(employeeId),
    [],
  );

  useEffect(() => {
    if (selectedEmployeeId !== null) {
      loadBalancesCallback(selectedEmployeeId);
    }
  }, [selectedEmployeeId, loadBalancesCallback]);

  async function onAction(
    request: LeaveRequest,
    action: "approve" | "reject" | "cancel",
  ) {
    if (busyId) return;
    setBusyId(request.id);
    setNotice(null);
    const optimistic: LeaveRequestStatus =
      action === "approve" ? "approved" : action === "reject" ? "rejected" : "cancelled";
    setStatus((current) =>
      current.state === "ready"
        ? {
            ...current,
            requests: current.requests.map((item) =>
              item.id === request.id ? { ...item, status: optimistic } : item,
            ),
          }
        : current,
    );
    try {
      if (action === "approve") await approveLeaveRequest(request.id);
      else if (action === "reject") await rejectLeaveRequest(request.id);
      else await cancelLeaveRequest(request.id);
      setNotice({
        tone: "success",
        text: `Request ${optimistic}.`,
      });
      await load();
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "The action failed.",
      });
      await load();
    } finally {
      setBusyId(null);
    }
  }

  const columns: ErpColumn<LeaveRequest>[] = [
    {
      key: "employeeId",
      label: "Employee",
      render: (request) => (
        <span className="font-medium text-foreground">
          {employeeName(request.employeeId) ?? request.employeeId}
        </span>
      ),
    },
    {
      key: "leaveType",
      label: "Type",
      render: (request) => (
        <span className="text-muted-foreground">{request.leaveType}</span>
      ),
    },
    {
      key: "startDate",
      label: "Dates",
      render: (request) => (
        <span className="text-muted-foreground">
          {formatDate(request.startDate)} → {formatDate(request.endDate)}
          <span className="ml-1 text-xs">({request.days}d)</span>
        </span>
      ),
    },
    {
      key: "status",
      label: "Status",
      render: (request) => <StatusBadge status={request.status} />,
    },
    {
      key: "createdAt",
      label: "Requested",
      render: (request) => (
        <span className="text-muted-foreground">{formatDate(request.createdAt)}</span>
      ),
    },
    ...(canAct
      ? [
          {
            key: "id" as const,
            label: "",
            align: "right" as const,
            render: (request: LeaveRequest) => (
              <div className="flex items-center justify-end gap-1">
                {request.status === "pending" ? (
                  <>
                    {canApprove ? (
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={(event) => {
                          event.stopPropagation();
                          void onAction(request, "approve");
                        }}
                        aria-label="Approve leave request"
                        title="Approve"
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-emerald-500/15 hover:text-emerald-600 disabled:opacity-50"
                      >
                        {busyId === request.id ? (
                          <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
                        ) : (
                          <Check aria-hidden="true" className="size-3.5" />
                        )}
                      </button>
                    ) : null}
                    {canApprove ? (
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={(event) => {
                          event.stopPropagation();
                          void onAction(request, "reject");
                        }}
                        aria-label="Reject leave request"
                        title="Reject"
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-red-500/15 hover:text-red-600 disabled:opacity-50"
                      >
                        {busyId === request.id ? (
                          <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
                        ) : (
                          <X aria-hidden="true" className="size-3.5" />
                        )}
                      </button>
                    ) : null}
                    {canWrite && !canApprove ? (
                      <button
                        type="button"
                        disabled={busyId !== null}
                        onClick={(event) => {
                          event.stopPropagation();
                          void onAction(request, "cancel");
                        }}
                        aria-label="Cancel leave request"
                        title="Cancel"
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                      >
                        {busyId === request.id ? (
                          <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin" />
                        ) : (
                          <X aria-hidden="true" className="size-3.5" />
                        )}
                      </button>
                    ) : null}
                  </>
                ) : null}
              </div>
            ),
          },
        ]
      : []),
  ];

  function openAdjust() {
    setAdjust({
      leaveType: balances[0]?.leaveType ?? "",
      qty: "",
      reason: "",
    });
    setAdjustError(null);
    setAdjustOpen(true);
  }

  async function onSubmitAdjust(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEmployeeId || adjustSaving) return;
    if (!adjust.leaveType || !adjust.qty.trim()) {
      setAdjustError("Leave type and quantity are required.");
      return;
    }
    const qty = Number(adjust.qty);
    if (!Number.isFinite(qty)) {
      setAdjustError("Quantity must be a number.");
      return;
    }
    if (qty === 0) {
      setAdjustError("Quantity can't be zero.");
      return;
    }
    setAdjustSaving(true);
    setAdjustError(null);
    try {
      await adjustLeaveBalance({
        employeeId: selectedEmployeeId,
        leaveType: adjust.leaveType,
        qty,
        reason: adjust.reason.trim(),
      });
      setAdjustOpen(false);
      setNotice({ tone: "success", text: `Balance adjusted for ${adjust.leaveType}.` });
      await loadBalances(selectedEmployeeId);
    } catch (error) {
      setAdjustError(
        error instanceof ApiError ? error.message : "Could not adjust the balance.",
      );
    } finally {
      setAdjustSaving(false);
    }
  }

  async function onAccrue() {
    if (!selectedEmployeeId || accruing) return;
    setAccruing(true);
    setNotice(null);
    try {
      await accrueLeave({ employeeId: selectedEmployeeId });
      setNotice({ tone: "success", text: "Leave accrued for this period." });
      await loadBalances(selectedEmployeeId);
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not accrue leave.",
      });
    } finally {
      setAccruing(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave"
        description="Requests, approvals, and every team member's balances."
        icon={CalendarDays}
      />

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

      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            Requests
          </h2>
          <div className="flex flex-wrap items-center gap-3">
            <Select
              value={statusFilter}
              onValueChange={(value) => {
                setStatusFilter(value as "all" | LeaveRequestStatus);
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
              value={employeeFilter}
              onValueChange={(value) => {
                setEmployeeFilter(value);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-48" aria-label="Filter by employee">
                <SelectValue placeholder="Employee" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All employees</SelectItem>
                {employees.map((employee) => (
                  <SelectItem key={employee.id} value={employee.id}>
                    {employee.firstName} {employee.lastName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
              rows={status.requests}
              meta={{
                total: status.requests.length,
                page,
                page_size: PAGE_SIZE,
                total_pages: status.totalPages,
              }}
              onPageChange={setPage}
            />
          ) : null}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
            Balances
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={selectedEmployeeId ?? ""}
              onValueChange={(value) => setSelectedEmployeeId(value || null)}
            >
              <SelectTrigger className="w-56" aria-label="Select employee">
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
            {canWrite ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setLogOpen(true)}
                >
                  Log leave
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={selectedEmployeeId === null}
                  onClick={openAdjust}
                >
                  Adjust balance
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={selectedEmployeeId === null || accruing}
                  onClick={() => void onAccrue()}
                >
                  {accruing ? (
                    <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                  ) : null}
                  Accrue
                </Button>
              </>
            ) : null}
          </div>
        </div>

        <div className="mt-4">
          {selectedEmployeeId === null ? (
            <p className="text-sm text-muted-foreground">
              Choose an employee to see their leave balances.
            </p>
          ) : balancesLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : balances.length === 0 ? (
            <p className="text-sm text-muted-foreground">No balances on record.</p>
          ) : (
            <div className="divide-y divide-border">
              {balances.map((balance) => (
                <div
                  key={`${balance.employeeId}-${balance.leaveType}`}
                  className="flex items-center justify-between gap-4 py-2"
                >
                  <span className="text-sm text-muted-foreground">{balance.leaveType}</span>
                  <span className="text-sm font-medium tabular-nums text-foreground">
                    {balance.balance} days
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      <Dialog open={adjustOpen} onOpenChange={(open) => !adjustSaving && setAdjustOpen(open)}>
        <DialogContent className="sm:max-w-md">
          <form onSubmit={(event) => void onSubmitAdjust(event)}>
            <DialogHeader>
              <DialogTitle>Adjust leave balance</DialogTitle>
              <DialogDescription>
                Add or remove days from the employee&apos;s balance. Negative
                quantities deduct days.
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="space-y-1.5">
                <Label htmlFor="adjust-type">Leave type</Label>
                <Select
                  value={adjust.leaveType}
                  onValueChange={(value) =>
                    setAdjust((current) => ({ ...current, leaveType: value }))
                  }
                >
                  <SelectTrigger id="adjust-type" className="w-full">
                    <SelectValue placeholder="Leave type" />
                  </SelectTrigger>
                  <SelectContent>
                    {balances.map((balance) => (
                      <SelectItem key={balance.leaveType} value={balance.leaveType}>
                        {balance.leaveType}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="adjust-qty">Days</Label>
                <Input
                  id="adjust-qty"
                  inputMode="decimal"
                  placeholder="e.g. -2 or 1.5"
                  value={adjust.qty}
                  onChange={(event) =>
                    setAdjust((current) => ({ ...current, qty: event.target.value }))
                  }
                  required
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="adjust-reason">Reason</Label>
                <Input
                  id="adjust-reason"
                  value={adjust.reason}
                  onChange={(event) =>
                    setAdjust((current) => ({ ...current, reason: event.target.value }))
                  }
                  placeholder="e.g. Carryover from last year"
                  required
                />
              </div>
            </div>
            {adjustError ? (
              <p role="alert" className="mb-2 text-sm font-medium text-destructive">
                {adjustError}
              </p>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setAdjustOpen(false)}
                disabled={adjustSaving}
              >
                Cancel
              </Button>
              <Button type="submit" disabled={adjustSaving}>
                {adjustSaving ? (
                  <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                ) : null}
                Apply adjustment
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <LogLeaveDialog
        open={logOpen}
        onOpenChange={setLogOpen}
        employees={employees}
        prefillEmployeeId={selectedEmployeeId}
        onCreated={() => void load()}
      />
    </div>
  );
}
