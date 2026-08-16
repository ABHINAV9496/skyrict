/**
 * Display labels and badge tones for CRM & Sales status values.
 *
 * Mirrors the `roleDisplayName`/`roleBadgeClass` pattern from identity-api.ts:
 * every enum member gets a human label and a translucent, ring-based badge
 * class that works in both light and dark themes.
 */

import type {
  CreditCheckResult,
  LeadStatus,
  OpportunityStage,
  OrderStatus,
} from "@/lib/api/crm-api";

export const LEAD_STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  contacted: "Contacted",
  qualified: "Qualified",
  disqualified: "Disqualified",
};

export const OPPORTUNITY_STAGE_LABELS: Record<OpportunityStage, string> = {
  prospecting: "Prospecting",
  qualified: "Qualified",
  proposal: "Proposal",
  negotiation: "Negotiation",
  won: "Won",
  lost: "Lost",
};

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  draft: "Draft",
  confirmed: "Confirmed",
  fulfilled: "Fulfilled",
  cancelled: "Cancelled",
};

export const CREDIT_CHECK_LABELS: Record<CreditCheckResult, string> = {
  pending: "Credit check pending",
  passed: "Credit check passed",
  failed: "Credit check failed",
};

const NEUTRAL_BADGE = "bg-muted text-muted-foreground ring-1 ring-border";
const SKY_BADGE = "bg-sky-500/15 text-sky-700 ring-1 ring-sky-500/30 dark:text-sky-400";
const EMERALD_BADGE =
  "bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/30 dark:text-emerald-400";
const AMBER_BADGE =
  "bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/30 dark:text-amber-400";
const VIOLET_BADGE =
  "bg-violet-500/15 text-violet-700 ring-1 ring-violet-500/30 dark:text-violet-400";
const RED_BADGE = "bg-red-500/15 text-red-700 ring-1 ring-red-500/30 dark:text-red-400";

export function leadStatusBadgeClass(status: LeadStatus): string {
  switch (status) {
    case "new":
      return NEUTRAL_BADGE;
    case "contacted":
      return SKY_BADGE;
    case "qualified":
      return EMERALD_BADGE;
    case "disqualified":
      return RED_BADGE;
  }
}

export function opportunityStageBadgeClass(stage: OpportunityStage): string {
  switch (stage) {
    case "prospecting":
      return NEUTRAL_BADGE;
    case "qualified":
      return SKY_BADGE;
    case "proposal":
      return VIOLET_BADGE;
    case "negotiation":
      return AMBER_BADGE;
    case "won":
      return EMERALD_BADGE;
    case "lost":
      return RED_BADGE;
  }
}

export function orderStatusBadgeClass(status: OrderStatus): string {
  switch (status) {
    case "draft":
      return NEUTRAL_BADGE;
    case "confirmed":
      return SKY_BADGE;
    case "fulfilled":
      return EMERALD_BADGE;
    case "cancelled":
      return RED_BADGE;
  }
}

export function creditCheckBadgeClass(result: CreditCheckResult): string {
  switch (result) {
    case "pending":
      return NEUTRAL_BADGE;
    case "passed":
      return EMERALD_BADGE;
    case "failed":
      return RED_BADGE;
  }
}
