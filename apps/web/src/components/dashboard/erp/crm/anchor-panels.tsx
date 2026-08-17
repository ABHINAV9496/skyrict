"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  CalendarPlus,
  CheckCircle2,
  ClipboardList,
  LoaderCircle,
  StickyNote,
  Trash2,
} from "lucide-react";

import { ActivityFormDialog } from "@/components/dashboard/erp/crm/activity-form-dialog";
import { EmptyState } from "@/components/dashboard/erp/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  createNote,
  deleteNote,
  listNotes,
  listTimeline,
  type CrmEntityType,
  type CrmNote,
  type TimelineItem,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import {
  ACTIVITY_KIND_LABELS,
  timelineEventLabel,
  timelineSourceBadgeClass,
} from "@/lib/erp/labels";
import { formatDate } from "@/lib/erp/money";
import { cn } from "@/lib/utils";

interface AnchorCardProps {
  entityType: CrmEntityType;
  entityId: string;
  canWrite: boolean;
  onNotice?: (message: string) => void;
}

function PanelShell({
  title,
  icon: Icon,
  action,
  children,
}: {
  title: string;
  icon: typeof ClipboardList;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 font-display text-base font-semibold text-foreground">
          <Icon aria-hidden="true" className="size-4 text-primary" />
          {title}
        </h3>
        {action}
      </div>
      {children}
    </div>
  );
}

type NotesStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; notes: CrmNote[] };

export function NotesCard({ entityType, entityId, canWrite }: AnchorCardProps) {
  const [status, setStatus] = useState<NotesStatus>({ state: "loading" });
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listNotes({ entityType, entityId, limit: 100 });
      setStatus({ state: "ready", notes: result.data });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load notes.",
      });
    }
  }, [entityType, entityId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onAdd() {
    const body = value.trim();
    if (!body || saving) return;
    setSaving(true);
    try {
      await createNote({ entityType, entityId, body });
      setValue("");
      await load();
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not add the note.",
      });
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(note: CrmNote) {
    try {
      await deleteNote(note.id);
      await load();
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not delete the note.",
      });
    }
  }

  return (
    <PanelShell
      title="Notes"
      icon={StickyNote}
      action={
        canWrite ? (
          <Button type="button" size="sm" disabled={!value.trim() || saving} onClick={onAdd}>
            {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
            Add note
          </Button>
        ) : undefined
      }
    >
      {canWrite ? (
        <Textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Add a note…"
          rows={3}
          maxLength={4000}
          disabled={saving}
        />
      ) : null}

      {status.state === "loading" ? (
        <div className="space-y-2">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
        </div>
      ) : status.state === "error" ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive">
          {status.message}
        </p>
      ) : status.notes.length === 0 ? (
        <EmptyState
          icon={StickyNote}
          title="No notes yet"
          description="Notes are private to your workspace and never appear on customer-facing documents."
        />
      ) : (
        <ul className="space-y-3">
          {status.notes.map((note) => (
            <li
              key={note.id}
              className="flex items-start justify-between gap-3 rounded-xl border border-border bg-card p-4"
            >
              <div className="min-w-0">
                <p className="text-sm whitespace-pre-wrap text-foreground">{note.body}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {formatDate(note.createdAt)}
                </p>
              </div>
              {canWrite ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Delete note"
                  title="Delete note"
                  className="shrink-0"
                  onClick={() => void onDelete(note)}
                >
                  <Trash2 aria-hidden="true" className="size-3.5 text-muted-foreground" />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </PanelShell>
  );
}

type TimelineStatus =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; items: TimelineItem[] };

export function TimelineCard({ entityType, entityId, canWrite }: AnchorCardProps) {
  const [status, setStatus] = useState<TimelineStatus>({ state: "loading" });
  const [activityOpen, setActivityOpen] = useState(false);

  const load = useCallback(async () => {
    setStatus({ state: "loading" });
    try {
      const result = await listTimeline(entityType, entityId, { limit: 100 });
      setStatus({ state: "ready", items: result.data });
    } catch (error) {
      setStatus({
        state: "error",
        message: error instanceof ApiError ? error.message : "Could not load the timeline.",
      });
    }
  }, [entityType, entityId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <PanelShell
      title="Relationship timeline"
      icon={ClipboardList}
      action={
        canWrite ? (
          <Button type="button" size="sm" onClick={() => setActivityOpen(true)}>
            <CalendarPlus aria-hidden="true" className="size-4" />
            Log activity
          </Button>
        ) : undefined
      }
    >
      {status.state === "loading" ? (
        <div className="space-y-2">
          <Skeleton className="h-20 rounded-xl" />
          <Skeleton className="h-20 rounded-xl" />
        </div>
      ) : status.state === "error" ? (
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive">
          {status.message}
        </p>
      ) : status.items.length === 0 ? (
        <EmptyState
          icon={ClipboardList}
          title="No timeline yet"
          description="Activities, notes, and business events for this record will appear here in one feed."
        />
      ) : (
        <ol className="space-y-3">
          {status.items.map((item) => (
            <li
              key={`${item.source}-${item.id}`}
              className="flex items-start gap-3 rounded-xl border border-border bg-card p-4"
            >
              <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                {item.source === "event" ? (
                  <CheckCircle2 aria-hidden="true" className="size-4" />
                ) : item.source === "note" ? (
                  <StickyNote aria-hidden="true" className="size-4" />
                ) : (
                  <ClipboardList aria-hidden="true" className="size-4" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className={timelineSourceBadgeClass(item.source)}>
                    {item.source === "activity" && item.kind
                      ? ACTIVITY_KIND_LABELS[item.kind as keyof typeof ACTIVITY_KIND_LABELS] ??
                        item.kind
                      : item.source === "event"
                        ? timelineEventLabel(item.kind)
                        : "Note"}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {formatDate(item.occurredAt)}
                  </span>
                </div>
                {item.source === "note" ? (
                  <p className="mt-1.5 text-sm whitespace-pre-wrap text-foreground">
                    {item.body}
                  </p>
                ) : (
                  <>
                    {item.title ? (
                      <p className="mt-1.5 text-sm font-medium text-foreground">{item.title}</p>
                    ) : null}
                    {item.body ? (
                      <p className="mt-1 text-sm whitespace-pre-wrap text-muted-foreground">
                        {item.body}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}

      <ActivityFormDialog
        open={activityOpen}
        onOpenChange={setActivityOpen}
        entityType={entityType}
        entityId={entityId}
        onSaved={async () => {
          await load();
        }}
      />
    </PanelShell>
  );
}

type RelationshipTab = "timeline" | "notes";

const RELATIONSHIP_TABS: { key: RelationshipTab; label: string }[] = [
  { key: "timeline", label: "Timeline" },
  { key: "notes", label: "Notes" },
];

/**
 * Tabbed Notes + Timeline workspace for any CRM anchor (lead / opportunity /
 * customer). Used by the lead and opportunity detail pages.
 */
export function RelationshipTabs({ entityType, entityId, canWrite }: AnchorCardProps) {
  const [tab, setTab] = useState<RelationshipTab>("timeline");

  return (
    <div className="space-y-4">
      <nav
        aria-label="Record workspace"
        className="flex items-center gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1"
      >
        {RELATIONSHIP_TABS.map((item) => {
          const active = tab === item.key;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => setTab(item.key)}
              aria-current={active ? "page" : undefined}
              className={cn(
                "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </nav>
      {tab === "timeline" ? (
        <TimelineCard entityType={entityType} entityId={entityId} canWrite={canWrite} />
      ) : (
        <NotesCard entityType={entityType} entityId={entityId} canWrite={canWrite} />
      )}
    </div>
  );
}
