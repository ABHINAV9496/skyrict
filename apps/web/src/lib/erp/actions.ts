/**
 * Pure domain rules for CRM & Sales UI actions.
 *
 * These matrices mirror the backend state machines (CRM-BE-002): leads move
 * new/contacted -> qualified | disqualified; the pipeline moves forward one
 * stage at a time and terminates at won/lost; orders follow
 * draft -> confirmed -> fulfilled with a terminal cancelled.
 *
 * Keeping them pure means the UI cannot drift from the documented transitions
 * and the matrices are unit-testable without a backend.
 */

import type { LeadStatus, OpportunityStage, OrderStatus } from "@/lib/api/crm-api";

export interface LeadActions {
  qualify: boolean;
  disqualify: boolean;
}

export function leadActions(status: LeadStatus): LeadActions {
  switch (status) {
    case "new":
    case "contacted":
      return { qualify: true, disqualify: true };
    default:
      return { qualify: false, disqualify: false };
  }
}

/** The pipeline columns in order - the board renders one per stage. */
export const PIPELINE_STAGES: OpportunityStage[] = [
  "prospecting",
  "qualified",
  "proposal",
  "negotiation",
  "won",
  "lost",
];

export function isTerminalStage(stage: OpportunityStage): boolean {
  return stage === "won" || stage === "lost";
}

/** Allowed forward transitions from a stage. Won/lost are terminal. */
const FORWARD_TRANSITIONS: Record<OpportunityStage, OpportunityStage[]> = {
  prospecting: ["qualified"],
  qualified: ["proposal"],
  proposal: ["negotiation"],
  negotiation: ["won", "lost"],
  won: [],
  lost: [],
};

export function nextStages(stage: OpportunityStage): OpportunityStage[] {
  return FORWARD_TRANSITIONS[stage];
}

export interface OrderActions {
  confirm: boolean;
  fulfil: boolean;
  cancel: boolean;
}

export function orderActions(status: OrderStatus): OrderActions {
  switch (status) {
    case "draft":
      return { confirm: true, fulfil: false, cancel: true };
    case "confirmed":
      return { confirm: false, fulfil: true, cancel: true };
    default:
      return { confirm: false, fulfil: false, cancel: false };
  }
}
