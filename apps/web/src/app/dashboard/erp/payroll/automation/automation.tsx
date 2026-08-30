"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock, Plus, Play, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/dashboard/shared/page-header";
import {
  ErpDataTable,
  ErpDataTableSkeleton,
  type ErpColumn,
} from "@/components/dashboard/shared/erp-data-table";
import {
  SearchableSelect,
  type SearchableSelectOption,
} from "@/components/dashboard/shared/searchable-select";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useModuleAccess } from "@/lib/access/modules";
import {
  createPayrollSchedule,
  deletePayrollSchedule,
  getPayrollPreferences,
  listPayrollNotifications,
  listPayrollSchedules,
  runPayrollAutomationTick,
  updatePayrollPreferences,
  updatePayrollSchedule,
  type PayrollNotification,
  type PayrollNotificationEventType,
  type PayrollPreferences,
  type PayrollSchedule,
} from "@/lib/api/payroll-automation-api";
import { ApiError } from "@/lib/api/http";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const DEFAULT_CRON = "0 18 1 * *";

type ScheduleRow = PayrollSchedule & { id: string };
type NotificationRow = PayrollNotification & { id: string };

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | {
      state: "ready";
      schedules: PayrollSchedule[];
      notifications: PayrollNotification[];
      preferences: PayrollPreferences | null;
    };

type Notice = { tone: "success" | "error"; text: string };

const NOTIFICATION_OPTIONS: { value: "all" | PayrollNotificationEventType; label: string }[] = [
  { value: "all", label: "All events" },
  { value: "payslip_ready", label: "Payslip ready" },
  { value: "payroll_batch_digest", label: "Batch digest" },
];

/** Month-at-a-glance: which days this month have an enabled schedule firing. */
function ScheduleCalendar({ schedules }: { schedules: PayrollSchedule[] }) {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth();
  const firstWeekday = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const firingDays = useMemo(() => {
    const set = new Set<number>();
    for (const schedule of schedules) {
      if (!schedule.enabled || !schedule.nextRunAt) continue;
      const date = new Date(schedule.nextRunAt);
      if (
        date.getFullYear() === year &&
        date.getMonth() === month &&
        !Number.isNaN(date.getTime())
      ) {
        set.add(date.getDate());
      }
    }
    return set;
  }, [schedules, year, month]);

  const weekdayLabels = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
  const cells: (number | null)[] = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs font-medium text-muted-foreground">
        {new Date(year, month, 1).toLocaleString(undefined, {
          month: "long",
          year: "numeric",
        })}
        {" — upcoming scheduled runs"}
      </p>
      <div className="mt-3 grid grid-cols-7 gap-1 text-center text-xs">
        {weekdayLabels.map((label) => (
          <span key={label} className="py-1 font-medium text-muted-foreground">
            {label}
          </span>
        ))}
        {cells.map((day, index) => {
          if (day === null) return <span key={`blank-${index}`} aria-hidden="true" />;
          const isFiring = firingDays.has(day);
          const isToday = day === now.getDate();
          return (
            <span
              key={day}
              className={cn(
                "relative inline-flex h-9 items-center justify-center rounded-md",
                isToday ? "bg-primary/10 font-semibold text-primary" : "text-foreground",
                isFiring ? "bg-emerald-500/15 font-medium text-emerald-700 dark:text-emerald-400" : "",
              )}
            >
              {day}
              {isFiring ? <span className="absolute bottom-1 size-1 rounded-full bg-emerald-500" /> : null}
            </span>
          );
        })}
      </div>
      <div className="mt-3 space-y-1 border-t border-border pt-3">
        {schedules.filter((s) => s.enabled && s.nextRunAt).length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No enabled schedules with a next run yet.
          </p>
        ) : (
          schedules
            .filter((s) => s.enabled && s.nextRunAt)
            .map((schedule) => (
              <p key={schedule.scheduleId} className="flex items-center justify-between text-xs">
                <span className="text-foreground">{schedule.name ?? schedule.cronExpression}</span>
                <span className="tabular-nums text-muted-foreground">
                  {formatDateTime(schedule.nextRunAt)}
                </span>
              </p>
            ))
        )}
      </div>
    </div>
  );
}

function ScheduleForm({
  onCreated,
}: {
  onCreated: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [cron, setCron] = useState(DEFAULT_CRON);
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    if (!cron.trim()) {
      setError("A cron expression is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const schedule = await createPayrollSchedule({
        name: name.trim() || undefined,
        cronExpression: cron.trim(),
        enabled,
      });
      setOpen(false);
      setName("");
      setCron(DEFAULT_CRON);
      setEnabled(true);
      onCreated(
        `${schedule.name ?? schedule.cronExpression} scheduled${
          schedule.enabled ? "" : " (paused)"
        }.`,
      );
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not create the schedule.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <Button type="button" onClick={() => setOpen(true)}>
        <Plus aria-hidden="true" className="size-4" />
        New schedule
      </Button>
    );
  }

  return (
    <form
      onSubmit={(event) => void onSubmit(event)}
      className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4"
    >
      <div className="space-y-1.5">
        <Label htmlFor="schedule-name">Name</Label>
        <Input
          id="schedule-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Monthly close"
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="schedule-cron">Cron (UTC)</Label>
        <Input
          id="schedule-cron"
          value={cron}
          onChange={(event) => setCron(event.target.value)}
          placeholder={DEFAULT_CRON}
          className="font-mono"
          required
        />
      </div>
      <label className="flex h-8 items-center gap-2 pb-px text-sm text-muted-foreground">
        <Checkbox checked={enabled} onCheckedChange={(value) => setEnabled(value === true)} />
        Enabled
      </label>
      {error ? (
        <p role="alert" className="w-full text-sm font-medium text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex items-center gap-2">
        <Button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Create"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => setOpen(false)}
          disabled={saving}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

const PAGE_SIZE = 20;

export function AutomationClient() {
  const { permissions } = useModuleAccess();
  const canRun = permissions.includes("*") || permissions.includes("erp.payroll.ai.run");
  const canNotify =
    permissions.includes("*") || permissions.includes("erp.payroll.ai.notify");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [notice, setNotice] = useState<Notice | null>(null);
  const [notificationFilter, setNotificationFilter] = useState<
    "all" | PayrollNotificationEventType
  >("all");

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    const [scheduleResult, notificationResult, preferenceResult] =
      await Promise.allSettled([
        listPayrollSchedules(),
        listPayrollNotifications({ limit: PAGE_SIZE }),
        getPayrollPreferences(),
      ]);

    if (scheduleResult.status === "rejected") {
      const error = scheduleResult.reason;
      setStatus({
        state: "error",
        message:
          error instanceof ApiError ? error.message : "Could not load payroll automation.",
      });
      return;
    }

    setStatus({
      state: "ready",
      schedules: scheduleResult.value,
      notifications:
        notificationResult.status === "fulfilled" ? notificationResult.value : [],
      preferences:
        preferenceResult.status === "fulfilled" ? preferenceResult.value : null,
    });
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const notificationOptions = useMemo<SearchableSelectOption[]>(
    () =>
      NOTIFICATION_OPTIONS.map((option) => ({
        value: option.value,
        label: option.label,
      })),
    [],
  );

  const filteredNotifications =
    status.state === "ready" && notificationFilter !== "all"
      ? status.notifications.filter((n) => n.eventType === notificationFilter)
      : status.state === "ready"
        ? status.notifications
        : [];

  const enabledSchedules =
    status.state === "ready" ? status.schedules.filter((s) => s.enabled) : [];

  const nextRunAt =
    status.state === "ready"
      ? enabledSchedules
          .map((s) => s.nextRunAt)
          .filter((value): value is string => Boolean(value))
          .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0] ?? null
      : null;

  const recentNotifications =
    status.state === "ready"
      ? status.notifications.filter((n) => {
          if (!n.createdAt) return false;
          const age = Date.now() - new Date(n.createdAt).getTime();
          return age >= 0 && age <= 7 * 24 * 60 * 60 * 1000;
        }).length
      : 0;

  async function onScheduleSaved(message: string) {
    setNotice({ tone: "success", text: message });
    await load();
  }

  async function toggleSchedule(schedule: PayrollSchedule) {
    try {
      await updatePayrollSchedule(schedule.scheduleId, {
        name: schedule.name ?? undefined,
        cronExpression: schedule.cronExpression,
        enabled: !schedule.enabled,
      });
      setNotice({
        tone: "success",
        text: `${schedule.name ?? schedule.cronExpression} ${
          schedule.enabled ? "paused" : "resumed"
        }.`,
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError ? error.message : "Could not update the schedule.",
      });
    }
    await load();
  }

  async function removeSchedule(schedule: PayrollSchedule) {
    if (!window.confirm(`Delete schedule "${schedule.name ?? schedule.cronExpression}"?`)) {
      return;
    }
    try {
      await deletePayrollSchedule(schedule.scheduleId);
      setNotice({ tone: "success", text: "Schedule deleted." });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError ? error.message : "Could not delete the schedule.",
      });
    }
    await load();
  }

  async function runTick() {
    setNotice(null);
    try {
      const tick = await runPayrollAutomationTick();
      const detail = [
        tick.itemsProcessed > 0 ? `${tick.itemsProcessed} items processed` : "queue empty",
        tick.schedulesFired > 0
          ? `${tick.schedulesFired} schedule${tick.schedulesFired === 1 ? "" : "s"} fired`
          : "no schedule due",
      ].join(", ");
      setNotice({
        tone: "success",
        text: `Tick complete — ${detail}.`,
      });
    } catch (error) {
      setNotice({
        tone: "error",
        text: error instanceof ApiError ? error.message : "Could not run the tick.",
      });
    }
    await load();
  }

  async function savePreferences(next: { inAppOn: boolean; emailOn: boolean }) {
    try {
      await updatePayrollPreferences(next);
      setNotice({ tone: "success", text: "Notification preferences saved." });
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError ? error.message : "Could not save preferences.",
      });
    }
    await load();
  }

  const notificationColumns: ErpColumn<NotificationRow>[] = [
    {
      key: "eventType",
      label: "Event",
      render: (item) => (
        <span
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
            item.eventType === "payslip_ready"
              ? "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400"
              : "bg-violet-500/15 text-violet-700 ring-1 ring-violet-500/30 dark:text-violet-400",
          )}
        >
          {item.eventType === "payslip_ready" ? "Payslip ready" : "Batch digest"}
        </span>
      ),
    },
    {
      key: "subject",
      label: "Subject",
      render: (item) => <span className="font-medium text-foreground">{item.subject}</span>,
    },
    {
      key: "inApp",
      label: "Delivery",
      render: (item) => (
        <span className="text-muted-foreground">
          {item.inApp ? "In-app" : item.emailStub ? "Email" : "—"}
        </span>
      ),
    },
    {
      key: "createdAt",
      label: "Created",
      render: (item) => (
        <span className="text-muted-foreground">{formatDateTime(item.createdAt)}</span>
      ),
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Payroll automation"
          description="Automated payroll batch runs, recurring schedules, and payslip notifications."
          icon={CalendarClock}
        />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-24 animate-pulse rounded-xl border border-border bg-card" />
        </div>
        <ErpDataTableSkeleton columns={4} />
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Payroll automation"
          description="Automated payroll batch runs, recurring schedules, and payslip notifications."
          icon={CalendarClock}
        />
        <div className="flex flex-col items-center justify-center rounded-xl border border-border bg-card px-4 py-10 text-center">
          <p className="text-sm font-medium text-destructive">{status.message}</p>
          <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const { schedules } = status;

  const scheduleColumns: ErpColumn<ScheduleRow>[] = [
    {
      key: "name",
      label: "Schedule",
      render: (schedule) => (
        <div>
          <p className="font-medium text-foreground">
            {schedule.name ?? <span className="text-muted-foreground">Unnamed</span>}
          </p>
          <p className="font-mono text-xs text-muted-foreground">{schedule.cronExpression}</p>
        </div>
      ),
    },
    {
      key: "enabled",
      label: "Status",
      render: (schedule) => (
        <button
          type="button"
          onClick={() => void toggleSchedule(schedule)}
          disabled={!canRun}
          title={canRun ? "Toggle this schedule" : "Needs erp.payroll.ai.run"}
          className={cn(
            "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 transition-colors",
            schedule.enabled
              ? "bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-400"
              : "bg-muted text-muted-foreground ring-border",
            canRun ? "hover:opacity-80" : "cursor-not-allowed opacity-60",
          )}
        >
          {schedule.enabled ? "Active" : "Paused"}
        </button>
      ),
    },
    {
      key: "lastFiredAt",
      label: "Last fired",
      render: (schedule) => (
        <span className="text-muted-foreground">
          {schedule.lastFiredAt ? formatDateTime(schedule.lastFiredAt) : "Never"}
        </span>
      ),
    },
    {
      key: "nextRunAt",
      label: "Next run",
      render: (schedule) => (
        <span className="tabular-nums text-muted-foreground">
          {schedule.nextRunAt ? formatDateTime(schedule.nextRunAt) : "—"}
        </span>
      ),
    },
    {
      key: "id",
      label: "",
      align: "right",
      render: (schedule) =>
        canRun ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Delete ${schedule.name ?? "schedule"}`}
            onClick={() => void removeSchedule(schedule)}
            className="text-muted-foreground hover:text-destructive"
          >
            <Trash2 aria-hidden="true" className="size-4" />
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHeader
          title="Payroll automation"
          description="Automated payroll batch runs, recurring schedules, and payslip notifications."
          icon={CalendarClock}
        />
        {canRun ? (
          <Button type="button" variant="outline" onClick={() => void runTick()}>
            <Play aria-hidden="true" className="size-4" />
            Run now
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

      <section aria-label="Automation summary" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Active schedules</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{enabledSchedules.length}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Next run</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">
            {nextRunAt ? formatDate(nextRunAt) : "—"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Notifications (7d)</p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">{recentNotifications}</p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground">Digest channel</p>
          <p className="mt-2 text-2xl font-semibold">
            {status.preferences?.inAppOn ? "In-app" : "Off"}
          </p>
        </div>
      </section>

      <section aria-label="Schedules" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
              Recurring schedules
            </h2>
            <p className="text-xs text-muted-foreground">
              Cron-based payroll submissions run by the background worker.
            </p>
          </div>
          {canRun ? <ScheduleForm onCreated={(message) => void onScheduleSaved(message)} /> : null}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <ScheduleCalendar schedules={schedules} />
          <div className="min-w-0">
            <ErpDataTable
              columns={scheduleColumns}
              rows={schedules.map((schedule) => ({ id: schedule.scheduleId, ...schedule }))}
              meta={{ total: schedules.length, page: 1, page_size: schedules.length, total_pages: 1 }}
              onPageChange={() => undefined}
            />
          </div>
        </div>
      </section>

      <section aria-label="Delivery preferences" className="space-y-3">
        <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
          Notification preferences
        </h2>
        <div className="rounded-xl border border-border bg-card p-4">
          {canNotify ? (
            <div className="flex flex-wrap items-center gap-6">
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={status.preferences?.inAppOn ?? true}
                  onCheckedChange={(value) =>
                    void savePreferences({
                      inAppOn: value === true,
                      emailOn: status.preferences?.emailOn ?? false,
                    })
                  }
                />
                In-app notifications
              </label>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={status.preferences?.emailOn ?? false}
                  onCheckedChange={(value) =>
                    void savePreferences({
                      inAppOn: status.preferences?.inAppOn ?? true,
                      emailOn: value === true,
                    })
                  }
                />
                Email (stub)
              </label>
              <p className="text-xs text-muted-foreground">
                Preferences are per user and self-scoped.
              </p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              Managing delivery preferences needs the erp.payroll.ai.notify permission.
            </p>
          )}
        </div>
      </section>

      <section aria-label="Notifications" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-display text-sm font-semibold tracking-tight text-foreground">
              Recent notifications
            </h2>
            <p className="text-xs text-muted-foreground">
              Payslip-ready alerts and payroll batch digests for your users.
            </p>
          </div>
          <SearchableSelect
            className="w-44"
            options={notificationOptions}
            value={notificationFilter}
            onValueChange={(value) =>
              setNotificationFilter(value as "all" | PayrollNotificationEventType)
            }
            placeholder="Event type"
          />
        </div>
        <ErpDataTable
          columns={notificationColumns}
          rows={filteredNotifications.map((item) => ({ id: item.notificationId, ...item }))}
          meta={{
            total: filteredNotifications.length,
            page: 1,
            page_size: PAGE_SIZE,
            total_pages: 1,
          }}
          onPageChange={() => undefined}
        />
      </section>
    </div>
  );
}