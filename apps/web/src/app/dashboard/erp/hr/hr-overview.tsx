"use client";

import { useCallback, useEffect, useState } from "react";
import { Building2, CalendarCheck2, CalendarDays, UserRound, Users } from "lucide-react";

import { RecentActivityList, type ActivityItem } from "@/components/dashboard/shared/recent-activity-list";
import { StatCard } from "@/components/dashboard/shared/stat-card";
import { StatusBreakdown, type BreakdownSegment } from "@/components/dashboard/shared/status-breakdown";
import { Button } from "@/components/ui/button";
import { CardSkeleton, StatCardSkeleton } from "@/components/ui/page-skeletons";
import {
  listDepartments,
  listEmployees,
  listLeaveRequests,
  type LeaveRequestStatus,
} from "@/lib/api/hr-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatDateTime, formatListCount } from "@/lib/format";

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; data: OverviewData };

interface OverviewData {
  activeEmployees: string;
  openLeave: string;
  onLeaveNow: string;
  departmentCount: number;
  leaveBreakdown: BreakdownSegment[];
  leaveTotal: number;
  recentLeave: ActivityItem[];
}

/** Bar/dot colors for the leave-by-status summary, matching StatusBadge hues. */
const STATUS_BAR: Record<LeaveRequestStatus, string> = {
  pending: "bg-amber-500",
  approved: "bg-emerald-500",
  rejected: "bg-red-500",
  cancelled: "bg-slate-400",
};

function localDateString(date: Date): string {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

export function HrOverview() {
  const [status, setStatus] = useState<PageStatus>({ state: "loading" });

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const [
        employeesResult,
        activeResult,
        departments,
        pendingResult,
        approvedResult,
        rejectedResult,
        cancelledResult,
        recentResult,
      ] = await Promise.all([
        listEmployees({ pageSize: 100 }),
        listEmployees({ pageSize: 20, filters: { status: "active" } }),
        listDepartments(),
        listLeaveRequests({ pageSize: 20, filters: { status: "pending" } }),
        listLeaveRequests({ pageSize: 20, filters: { status: "approved" } }),
        listLeaveRequests({ pageSize: 20, filters: { status: "rejected" } }),
        listLeaveRequests({ pageSize: 20, filters: { status: "cancelled" } }),
        listLeaveRequests({ pageSize: 6 }),
      ]);

      const nameByEmployeeId = new Map(
        employeesResult.items.map((employee) => [employee.id, employee]),
      );
      const nameFor = (employeeId: string | null | undefined): string | null => {
        const employee = employeeId ? nameByEmployeeId.get(employeeId) : undefined;
        return employee ? `${employee.firstName} ${employee.lastName}` : null;
      };

      const today = localDateString(new Date());
      const awayToday = new Set<string>();
      for (const request of approvedResult.items) {
        if (request.startDate <= today && request.endDate >= today) {
          awayToday.add(request.employeeId);
        }
      }

      const recentLeave: ActivityItem[] = recentResult.items.map((request) => ({
        key: request.id,
        icon: <CalendarDays aria-hidden="true" className="size-4" />,
        title: nameFor(request.employeeId) ?? "Team member",
        meta: `${request.leaveType} · ${formatDate(request.startDate)} – ${formatDate(request.endDate)}`,
        status: request.status,
        time: formatDateTime(request.createdAt),
        href: "/dashboard/erp/hr/leave",
      }));

      const leaveBreakdown: BreakdownSegment[] = [
        {
          label: "Pending",
          value: pendingResult.meta.total,
          colorClass: STATUS_BAR.pending,
          href: "/dashboard/erp/hr/leave?status=pending",
        },
        {
          label: "Approved",
          value: approvedResult.meta.total,
          colorClass: STATUS_BAR.approved,
          href: "/dashboard/erp/hr/leave?status=approved",
        },
        {
          label: "Rejected",
          value: rejectedResult.meta.total,
          colorClass: STATUS_BAR.rejected,
          href: "/dashboard/erp/hr/leave?status=rejected",
        },
        {
          label: "Cancelled",
          value: cancelledResult.meta.total,
          colorClass: STATUS_BAR.cancelled,
          href: "/dashboard/erp/hr/leave?status=cancelled",
        },
      ];

      setStatus({
        state: "ready",
        data: {
          activeEmployees: formatListCount(activeResult.meta),
          openLeave: formatListCount(pendingResult.meta),
          onLeaveNow:
            awayToday.size > 0
              ? formatListCount(approvedResult.meta).includes("+")
                ? `${awayToday.size}+`
                : String(awayToday.size)
              : "0",
          departmentCount: departments.length,
          leaveBreakdown,
          leaveTotal:
            pendingResult.meta.total +
            approvedResult.meta.total +
            rejectedResult.meta.total +
            cancelledResult.meta.total,
          recentLeave,
        },
      });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load HR overview.",
      });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
          <StatCardSkeleton />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <CardSkeleton className="h-64" />
          <CardSkeleton className="h-64" />
        </div>
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-10 text-center">
        <p className="text-sm font-medium text-destructive">{status.message}</p>
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
          Try again
        </Button>
      </div>
    );
  }

  const { data } = status;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Users}
          label="Active employees"
          value={data.activeEmployees}
          hint="Currently on the team"
          href="/dashboard/erp/hr/employees"
        />
        <StatCard
          icon={CalendarCheck2}
          label="Open leave requests"
          value={data.openLeave}
          hint="Awaiting approval"
          href="/dashboard/erp/hr/leave?status=pending"
        />
        <StatCard
          icon={UserRound}
          label="On leave now"
          value={data.onLeaveNow}
          hint="Approved leave today"
          href="/dashboard/erp/hr/leave?status=approved"
        />
        <StatCard
          icon={Building2}
          label="Departments"
          value={String(data.departmentCount)}
          hint="Across the company"
          href="/dashboard/erp/hr/departments"
        />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <StatusBreakdown
          title="Leave requests by status"
          segments={data.leaveBreakdown}
          total={data.leaveTotal}
        />
        <RecentActivityList
          title="Recent leave activity"
          items={data.recentLeave}
          emptyMessage="No leave activity yet — hire a team member or create a leave request."
        />
      </div>
    </div>
  );
}
