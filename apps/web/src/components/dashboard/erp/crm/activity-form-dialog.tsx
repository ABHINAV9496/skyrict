"use client";

import { useEffect, useState } from "react";
import { CalendarPlus, LoaderCircle } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import {
  createActivity,
  listContacts,
  listCustomers,
  listLeads,
  listOpportunities,
  updateActivity,
  type Activity,
  type ActivityInput,
  type ActivityKind,
  type CrmEntityType,
} from "@/lib/api/crm-api";
import { ApiError } from "@/lib/api/http";
import { ACTIVITY_KIND_LABELS, ENTITY_TYPE_LABELS } from "@/lib/erp/labels";
import { cn } from "@/lib/utils";

interface ActivityFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (activity: Activity) => void;
  /** Pre-selected anchor when the dialog is opened from a detail page. */
  entityType?: CrmEntityType | null;
  entityId?: string | null;
  /** When provided the dialog edits this activity instead of creating one. */
  activity?: Activity | null;
}

const KIND_OPTIONS: ActivityKind[] = ["task", "call", "meeting", "follow_up", "email", "note"];
const ENTITY_OPTIONS: CrmEntityType[] = ["lead", "opportunity", "customer", "contact"];

interface EntityOption {
  id: string;
  label: string;
}

function entityLabel(kind: CrmEntityType, option: EntityOption): string {
  if (kind === "lead") return option.label;
  if (kind === "opportunity") return option.label;
  return option.label;
}

/**
 * Create/edit activity dialog. Create needs an anchor (entity type + entity);
 * the entity list loads on demand when the type changes. Edit keeps the anchor
 * fixed — the backend only accepts anchor changes at creation.
 */
export function ActivityFormDialog({
  open,
  onOpenChange,
  onSaved,
  entityType,
  entityId,
  activity,
}: ActivityFormDialogProps) {
  const editing = Boolean(activity);
  const [kind, setKind] = useState<ActivityKind>("follow_up");
  const [anchorType, setAnchorType] = useState<CrmEntityType>("customer");
  const [anchorId, setAnchorId] = useState("");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [notes, setNotes] = useState("");
  const [entities, setEntities] = useState<EntityOption[]>([]);
  const [entitiesLoading, setEntitiesLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (open) {
      setKind(activity?.kind ?? "follow_up");
      setAnchorType(activity?.entityType ?? entityType ?? "customer");
      setAnchorId(activity?.entityId ?? entityId ?? "");
      setSubject(activity?.subject ?? "");
      setDescription(activity?.description ?? "");
      setDueAt(activity?.dueAt ? activity.dueAt.slice(0, 16) : "");
      setNotes(activity?.notes ?? "");
      setSaving(false);
      setNotice(null);
    }
  }, [open, activity, entityType, entityId]);

  useEffect(() => {
    if (!open || editing || !anchorType) return;
    let cancelled = false;
    setEntitiesLoading(true);
    setAnchorId("");
    (async () => {
      try {
        let options: EntityOption[];
        if (anchorType === "lead") {
          const result = await listLeads({ limit: 100 });
          options = result.data.map((lead) => ({
            id: lead.id,
            label:
              [lead.firstName, lead.lastName].filter(Boolean).join(" ") ||
              lead.company ||
              lead.email ||
              "Unnamed lead",
          }));
        } else if (anchorType === "opportunity") {
          const result = await listOpportunities({ limit: 100 });
          options = result.data.map((opportunity) => ({
            id: opportunity.id,
            label: opportunity.name || "Unnamed opportunity",
          }));
        } else if (anchorType === "customer") {
          const result = await listCustomers({ limit: 100 });
          options = result.data.map((customer) => ({
            id: customer.id,
            label: customer.name,
          }));
        } else {
          const result = await listContacts({ limit: 100 });
          options = result.data.map((contact) => ({
            id: contact.id,
            label:
              [contact.firstName, contact.lastName].filter(Boolean).join(" ") ||
              contact.email ||
              "Unnamed contact",
          }));
        }
        if (!cancelled) setEntities(options);
      } catch {
        if (!cancelled) setEntities([]);
      } finally {
        if (!cancelled) setEntitiesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, editing, anchorType]);

  const canSubmit =
    subject.trim().length > 0 && (editing || anchorId.length > 0) && !saving;

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

    setSaving(true);
    setNotice(null);
    try {
      if (editing && activity) {
        const saved = await updateActivity(activity.id, {
          kind,
          subject: subject.trim(),
          description: description.trim() || undefined,
          dueAt: dueAt || undefined,
          notes: notes.trim() || undefined,
        });
        setNotice({ tone: "success", text: "Activity updated." });
        onSaved(saved);
        onOpenChange(false);
        return;
      }
      const input: ActivityInput = {
        kind,
        entityType: anchorType,
        entityId: anchorId,
        subject: subject.trim(),
        description: description.trim() || undefined,
        dueAt: dueAt || undefined,
        notes: notes.trim() || undefined,
      };
      const saved = await createActivity(input);
      setNotice({ tone: "success", text: "Activity created." });
      onSaved(saved);
      onOpenChange(false);
    } catch (error) {
      setNotice({
        tone: "error",
        text:
          error instanceof ApiError
            ? error.message
            : editing
              ? "Could not update the activity."
              : "Could not create the activity.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarPlus aria-hidden="true" className="size-4 text-primary" />
            {editing ? "Edit activity" : "New activity"}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? "Update the follow-up or interaction record."
              : "Follow-ups (task, follow_up) carry a due date; calls, meetings, and emails are interaction records."}
          </DialogDescription>
        </DialogHeader>

        <form id="activity-form" onSubmit={(event) => void onSubmit(event)} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="activity-kind">Type</Label>
              <Select value={kind} onValueChange={(value) => setKind(value as ActivityKind)} disabled={saving}>
                <SelectTrigger id="activity-kind" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KIND_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {ACTIVITY_KIND_LABELS[option]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="activity-due">Due</Label>
              <Input
                id="activity-due"
                type="datetime-local"
                value={dueAt}
                onChange={(event) => setDueAt(event.target.value)}
                disabled={saving}
              />
            </div>
          </div>

          {editing ? (
            <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm text-muted-foreground">
              Anchored to{" "}
              <span className="font-medium text-foreground">
                {ENTITY_TYPE_LABELS[anchorType]}
              </span>
              — the anchor cannot be moved.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="activity-entity-type">Linked to</Label>
                <Select
                  value={anchorType}
                  onValueChange={(value) => setAnchorType(value as CrmEntityType)}
                  disabled={saving}
                >
                  <SelectTrigger id="activity-entity-type" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ENTITY_OPTIONS.map((option) => (
                      <SelectItem key={option} value={option}>
                        {ENTITY_TYPE_LABELS[option]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="activity-entity">Entity</Label>
                {entitiesLoading ? (
                  <div className="h-8 rounded-lg bg-muted/60" />
                ) : (
                  <Select value={anchorId} onValueChange={setAnchorId} disabled={saving}>
                    <SelectTrigger id="activity-entity" className="w-full">
                      <SelectValue placeholder={entities.length === 0 ? "None available" : "Select…"} />
                    </SelectTrigger>
                    <SelectContent>
                      {entities.map((entity) => (
                        <SelectItem key={entity.id} value={entity.id}>
                          {entityLabel(anchorType, entity)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="activity-subject">Subject</Label>
            <Input
              id="activity-subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder={kind === "note" ? "e.g. Call summary" : "e.g. Follow up on proposal"}
              maxLength={255}
              disabled={saving}
              aria-required="true"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="activity-description">Description</Label>
            <Textarea
              id="activity-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Optional context — shown in the timeline"
              rows={3}
              maxLength={4000}
              disabled={saving}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="activity-notes">Notes</Label>
            <Textarea
              id="activity-notes"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Private notes — only teammates with access see these"
              rows={2}
              maxLength={4000}
              disabled={saving}
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
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="activity-form" disabled={!canSubmit}>
            {saving ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : null}
            {editing ? "Save changes" : "Create activity"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
