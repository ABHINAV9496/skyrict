"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CalendarClock, CheckCircle2, LoaderCircle, Pencil, Plus, Trash2 } from "lucide-react";

import { ErpTable, type ErpColumn } from "@/components/dashboard/erp/erp-table";
import { ErrorState } from "@/components/dashboard/erp/error-state";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { Pagination, offsetMeta } from "@/components/dashboard/erp/pagination";
import { ActivityFormDialog } from "@/components/dashboard/erp/crm/activity-form-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { TableSkeleton } from "@/components/ui/page-skeletons";
import { useModuleAccess } from "@/lib/access/modules";
import {
  completeActivity,
  deleteActivity,
  listActivities,
  type Activity,
  type ActivityKind,
  type ActivityStatus,
  type CrmEntityType,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { ACTIVITY_KIND_LABELS, activityKindBadgeClass, ENTITY_TYPE_LABELS } from "@/lib/erp/labels";
import { formatDate } from "@/lib/erp/money";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const STATUS_FILTERS: { value: ActivityStatus | "all"; label: string }[] = [
  { value: "all", label: "All activities" },
  { value: "open", label: "Open" },
  { value: "overdue", label: "Overdue" },
  { value: "today", label: "Due today" },
  { value: "upcoming", label: "Upcoming" },
  { value: "completed", label: "Completed" },
];

const KIND_FILTERS: ActivityKind[] = ["task", "call", "meeting", "follow_up", "email", "note"];
const ENTITY_FILTERS: CrmEntityType[] = ["lead", "opportunity", "customer", "contact"];

type PageStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; activities: Activity[]; total: number; notice?: string };

function anchorHref(activity: Activity): string | null {
  switch (activity.entityType) {
    case "lead":
      return `/dashboard/erp/crm/leads/${activity.entityId}`;
    case "opportunity":
      return `/dashboard/erp/crm/opportunities/${activity.entityId}`;
    case "customer":
      return `/dashboard/erp/crm/customers/${activity.entityId}`;
    case "contact":
      return null;
  }
}

export function ActivitiesTable() {
  const { permissions } = useModuleAccess();
  const canWrite = permissions.includes("*") || permissions.includes("erp.crm.write");

  const [status, setStatus] = useState<PageStatus>({ state: "loading" });
  const [statusFilter, setStatusFilter] = useState<ActivityStatus | "all">("all");
  const [kindFilter, setKindFilter] = useState<ActivityKind | "all">("all");
  const [entityFilter, setEntityFilter] = useState<CrmEntityType | "all">("all");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Activity | null>(null);
  const [deleting, setDeleting] = useState<Activity | null>(null);
  const [completingId, setCompletingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listActivities({
        status: statusFilter === "all" ? undefined : statusFilter,
        kind: kindFilter === "all" ? undefined : kindFilter,
        entityType: entityFilter === "all" ? undefined : entityFilter,
        offset,
        limit: PAGE_SIZE,
      });
      setStatus({ state: "ready", activities: result.data, total: result.meta.total });
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Could not load activities.";
      setStatus({ state: "error", message });
    }
  }, [statusFilter, kindFilter, entityFilter, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runAction(action: () => Promise<unknown>) {
    try {
      await action();
      await load();
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "The action could not be completed.";
      setStatus((current) =>
        current.state === "ready" ? { ...current, notice: message } : current,
      );
    }
  }

  async function onComplete(activity: Activity) {
    setCompletingId(activity.id);
    await runAction(() => completeActivity(activity.id));
    setCompletingId(null);
  }

  async function onDelete() {
    if (!deleting) return;
    setBusy(true);
    await runAction(() => deleteActivity(deleting.id));
    setBusy(false);
    setDeleting(null);
  }

  const columns: ErpColumn<Activity>[] = [
    {
      key: "subject",
      label: "Subject",
      render: (activity) => {
        const href = anchorHref(activity);
        const anchor = (
          <span className="text-xs text-muted-foreground">
            {ENTITY_TYPE_LABELS[activity.entityType]}
          </span>
        );
        return (
          <div className="min-w-0">
            <p className="truncate font-medium text-foreground">{activity.subject}</p>
            <p className="truncate text-xs text-muted-foreground">
              {href ? (
                <Link href={href} className="hover:text-primary">
                  {ENTITY_TYPE_LABELS[activity.entityType]} · {activity.entityId.slice(0, 8)}
                </Link>
              ) : (
                <span>
                  {anchor} · {activity.entityId.slice(0, 8)}
                </span>
              )}
            </p>
          </div>
        );
      },
    },
    {
      key: "kind",
      label: "Type",
      render: (activity) => (
        <Badge variant="outline" className={activityKindBadgeClass(activity.kind)}>
          {ACTIVITY_KIND_LABELS[activity.kind]}
        </Badge>
      ),
    },
    {
      key: "due",
      label: "Due",
      render: (activity) => {
        const overdue =
          activity.completedAt === null &&
          activity.dueAt !== null &&
          new Date(activity.dueAt).getTime() < Date.now();
        return (
          <span
            className={cn(
              "text-foreground tabular-nums",
              overdue && "font-medium text-destructive",
            )}
          >
            {formatDate(activity.dueAt)}
            {overdue ? " · overdue" : ""}
          </span>
        );
      },
    },
    {
      key: "status",
      label: "Status",
      render: (activity) =>
        activity.completedAt !== null ? (
          <Badge
            variant="outline"
            className="bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400"
          >
            Completed
          </Badge>
        ) : (
          <Badge variant="outline" className="bg-muted text-muted-foreground ring-1 ring-border">
            Open
          </Badge>
        ),
    },
    {
      key: "actions",
      label: "Actions",
      align: "right",
      className: "w-32",
      render: (activity) =>
        canWrite ? (
          <div className="flex items-center justify-end gap-1">
            {activity.completedAt === null ? (
              <Button
                type="button"
                variant="outline"
                size="xs"
                disabled={completingId !== null || busy}
                onClick={(event) => {
                  event.stopPropagation();
                  void onComplete(activity);
                }}
              >
                {completingId === activity.id ? (
                  <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />
                ) : (
                  <CheckCircle2 aria-hidden="true" className="size-3" />
                )}
                Complete
              </Button>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label="Edit activity"
              title="Edit activity"
              onClick={(event) => {
                event.stopPropagation();
                setEditing(activity);
              }}
            >
              <Pencil aria-hidden="true" className="size-3.5 text-muted-foreground" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label="Delete activity"
              title="Delete activity"
              onClick={(event) => {
                event.stopPropagation();
                setDeleting(activity);
              }}
            >
              <Trash2 aria-hidden="true" className="size-3.5 text-muted-foreground" />
            </Button>
          </div>
        ) : null,
    },
  ];

  if (status.state === "loading") {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="h-8 w-40 rounded-lg bg-muted/70" />
            <div className="h-8 w-36 rounded-lg bg-muted/70" />
            <div className="h-8 w-40 rounded-lg bg-muted/70" />
          </div>
          <div className="h-8 w-28 rounded-lg bg-muted/70" />
        </div>
        <TableSkeleton rows={6} />
      </div>
    );
  }

  if (status.state === "error") {
    return <ErrorState message={status.message} onRetry={() => void load()} />;
  }

  const hasFilters = statusFilter !== "all" || kindFilter !== "all" || entityFilter !== "all";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={statusFilter}
            onValueChange={(value) => {
              setStatusFilter(value as ActivityStatus | "all");
              setOffset(0);
            }}
          >
            <SelectTrigger className="w-40" aria-label="Filter by status">
              <SelectValue placeholder="All activities" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((filter) => (
                <SelectItem key={filter.value} value={filter.value}>
                  {filter.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={kindFilter}
            onValueChange={(value) => {
              setKindFilter(value as ActivityKind | "all");
              setOffset(0);
            }}
          >
            <SelectTrigger className="w-36" aria-label="Filter by type">
              <SelectValue placeholder="All types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All types</SelectItem>
              {KIND_FILTERS.map((kind) => (
                <SelectItem key={kind} value={kind}>
                  {ACTIVITY_KIND_LABELS[kind]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={entityFilter}
            onValueChange={(value) => {
              setEntityFilter(value as CrmEntityType | "all");
              setOffset(0);
            }}
          >
            <SelectTrigger className="w-40" aria-label="Filter by linked entity">
              <SelectValue placeholder="All linked entities" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All entities</SelectItem>
              {ENTITY_FILTERS.map((entity) => (
                <SelectItem key={entity} value={entity}>
                  {ENTITY_TYPE_LABELS[entity]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {canWrite ? (
          <Button type="button" onClick={() => setCreateOpen(true)}>
            <Plus aria-hidden="true" className="size-4" />
            New activity
          </Button>
        ) : null}
      </div>

      {status.notice ? (
        <div
          role="alert"
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive"
        >
          {status.notice}
        </div>
      ) : null}

      {status.activities.length === 0 ? (
        <EmptyState
          icon={CalendarClock}
          title={hasFilters ? "No matching activities" : "No activities yet"}
          description={
            hasFilters
              ? "Try a different filter combination."
              : "Log a call or meeting, or schedule a follow-up to keep every relationship moving."
          }
          action={
            canWrite && !hasFilters ? (
              <Button type="button" variant="outline" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden="true" className="size-4" />
                New activity
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ErpTable
          columns={columns}
          rows={status.activities}
          rowKey={(activity) => activity.id}
          footer={
            <Pagination
              meta={offsetMeta(offset, PAGE_SIZE, status.total)}
              onPageChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
            />
          }
        />
      )}

      <ActivityFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onSaved={() => {
          setOffset(0);
          void load();
        }}
      />

      <ActivityFormDialog
        open={editing !== null}
        onOpenChange={(open) => !open && setEditing(null)}
        activity={editing}
        onSaved={() => void load()}
      />

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this activity?</DialogTitle>
            <DialogDescription>
              {deleting?.subject ?? "This activity"} is removed permanently - including from the
              relationship timeline.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleting(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={onDelete} disabled={busy}>
              {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
