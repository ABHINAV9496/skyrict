import type { ReactNode } from "react";

import {
  ENTRY_STATUS_LABELS,
  INVOICE_STATUS_LABELS,
  type EntryStatus,
  type InvoiceStatus,
} from "@/lib/finance/format";
import { cn } from "@/lib/utils";

type Tone = "muted" | "primary" | "success" | "warning" | "danger" | "info";

const toneConfig: Record<Tone, { dot: string; chip: string }> = {
  muted: { dot: "bg-muted-foreground/50", chip: "bg-muted text-muted-foreground" },
  primary: { dot: "bg-primary", chip: "bg-primary/10 text-primary" },
  success: {
    dot: "bg-emerald-500",
    chip: "bg-emerald-500/10 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  },
  warning: {
    dot: "bg-amber-500",
    chip: "bg-amber-500/10 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  },
  danger: {
    dot: "bg-red-500",
    chip: "bg-red-500/10 text-red-700 dark:bg-red-500/15 dark:text-red-300",
  },
  info: {
    dot: "bg-sky-500",
    chip: "bg-sky-500/10 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  },
};

export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  const config = toneConfig[tone];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
        config.chip,
      )}
    >
      <span aria-hidden="true" className={cn("size-1.5 rounded-full", config.dot)} />
      {children}
    </span>
  );
}

const entryTone: Record<EntryStatus, Tone> = {
  draft: "muted",
  posted: "success",
  voided: "danger",
  reversed: "warning",
};

export function EntryStatusBadge({ status }: { status: EntryStatus }) {
  return (
    <StatusBadge tone={entryTone[status]}>{ENTRY_STATUS_LABELS[status]}</StatusBadge>
  );
}

const invoiceTone: Record<InvoiceStatus, Tone> = {
  draft: "muted",
  issued: "info",
  approved: "primary",
  paid: "success",
  voided: "danger",
};

export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return (
    <StatusBadge tone={invoiceTone[status]}>{INVOICE_STATUS_LABELS[status]}</StatusBadge>
  );
}

export function ActiveBadge({ active }: { active: boolean }) {
  return active ? (
    <StatusBadge tone="success">Active</StatusBadge>
  ) : (
    <StatusBadge tone="muted">Inactive</StatusBadge>
  );
}
