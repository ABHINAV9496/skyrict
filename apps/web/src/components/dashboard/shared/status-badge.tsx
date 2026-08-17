import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** Tinted pill classes keyed by the ERP status strings (mirrors roleBadgeClass). */
const STATUS_CLASSES: Record<string, string> = {
  // Employee statuses
  active: "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  on_leave:
    "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  terminated: "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
  // Leave request statuses
  pending:
    "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400",
  approved:
    "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  rejected: "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
  cancelled: "bg-muted text-muted-foreground ring-1 ring-border",
  // Payroll run statuses
  draft: "bg-muted text-muted-foreground ring-1 ring-border",
  computed: "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400",
  paid: "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400",
  void: "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400",
};

const DEFAULT_CLASS = "bg-muted text-muted-foreground ring-1 ring-border";

function titleCase(status: string): string {
  return status
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** A tinted pill for an ERP status value (active, on_leave, approved, paid…). */
export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="secondary" className={cn(STATUS_CLASSES[status] ?? DEFAULT_CLASS)}>
      {titleCase(status)}
    </Badge>
  );
}
