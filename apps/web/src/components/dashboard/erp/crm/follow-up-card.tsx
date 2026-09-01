"use client";

import { useState } from "react";
import {
  CalendarClock,
  Check,
  Loader2,
  Mail,
  Phone,
  StickyNote,
  X,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/http";
import { applyFollowUp, dismissFollowUp, type FollowUpItem } from "@/lib/api/crm-ai-api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Follow-up type icons and labels
// ---------------------------------------------------------------------------

const TYPE_CONFIG: Record<string, { icon: typeof Mail; label: string; color: string }> = {
  email: {
    icon: Mail,
    label: "Email",
    color: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
  },
  call: {
    icon: Phone,
    label: "Call",
    color: "bg-violet-500/15 text-violet-700 ring-1 ring-violet-500/30 dark:text-violet-400",
  },
  meeting: {
    icon: CalendarClock,
    label: "Meeting",
    color: "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  },
  task: {
    icon: StickyNote,
    label: "Task",
    color: "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  },
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FollowUpCardProps {
  item: FollowUpItem;
  /** Called after apply/dismiss so the parent can refresh its list. */
  onAction?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FollowUpCard({ item, onAction }: FollowUpCardProps) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const config = TYPE_CONFIG[item.suggestion_type] ?? TYPE_CONFIG.task;
  const Icon = config.icon;

  const handleApply = async () => {
    setBusy(true);
    try {
      await applyFollowUp(item.id, item.entity_id);
      setDone(true);
      onAction?.();
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not apply follow-up.";
      // eslint-disable-next-line no-alert -- non-critical user feedback
      alert(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleDismiss = async () => {
    setBusy(true);
    try {
      await dismissFollowUp(item.id);
      setDone(true);
      onAction?.();
    } catch {
      // dismiss errors are non-fatal
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div className="rounded-xl border border-border bg-muted/30 p-4 opacity-60">
        <p className="text-xs text-muted-foreground italic">Handled</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className={cn("text-xs", config.color)}>
            <Icon aria-hidden="true" className="mr-1 size-3" />
            {config.label}
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            {item.entity_type}
          </Badge>
        </div>
        <span className="text-[10px] text-muted-foreground tabular-nums">
          {Math.round(item.confidence * 100)}%
        </span>
      </div>

      {/* Reasoning */}
      <p className="text-xs text-muted-foreground">{item.reasoning}</p>

      {/* Draft content */}
      <div className="rounded-lg bg-muted/50 p-3">
        <p className="text-xs font-medium text-foreground mb-1">Suggested message</p>
        <p className="text-xs text-muted-foreground whitespace-pre-wrap">{item.draft_content}</p>
      </div>

      {/* Actions */}
      <div className="flex gap-2 pt-1">
        <Button
          size="sm"
          variant="outline"
          className="flex-1"
          onClick={() => void handleApply()}
          disabled={busy}
        >
          {busy ? (
            <Loader2 aria-hidden="true" className="mr-1 size-3 animate-spin" />
          ) : (
            <Check aria-hidden="true" className="mr-1 size-3" />
          )}
          Apply
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="flex-1 text-muted-foreground"
          onClick={() => void handleDismiss()}
          disabled={busy}
        >
          <X aria-hidden="true" className="mr-1 size-3" />
          Dismiss
        </Button>
      </div>
    </div>
  );
}
