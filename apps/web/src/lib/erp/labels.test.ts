import { describe, expect, it } from "vitest";

import type {
  CreditCheckResult,
  LeadStatus,
  OpportunityStage,
  OrderStatus,
} from "@/lib/api/crm-api";
import {
  creditCheckBadgeClass,
  CREDIT_CHECK_LABELS,
  LEAD_STATUS_LABELS,
  leadStatusBadgeClass,
  OPPORTUNITY_STAGE_LABELS,
  opportunityStageBadgeClass,
  ORDER_STATUS_LABELS,
  orderStatusBadgeClass,
} from "@/lib/erp/labels";

describe("status labels", () => {
  it("labels every lead status", () => {
    const statuses: LeadStatus[] = ["new", "contacted", "qualified", "disqualified"];
    for (const status of statuses) {
      expect(LEAD_STATUS_LABELS[status]).toBeTruthy();
    }
  });

  it("labels every pipeline stage", () => {
    const stages: OpportunityStage[] = [
      "prospecting",
      "qualified",
      "proposal",
      "negotiation",
      "won",
      "lost",
    ];
    for (const stage of stages) {
      expect(OPPORTUNITY_STAGE_LABELS[stage]).toBeTruthy();
    }
  });

  it("labels every order status", () => {
    const statuses: OrderStatus[] = ["draft", "confirmed", "fulfilled", "cancelled"];
    for (const status of statuses) {
      expect(ORDER_STATUS_LABELS[status]).toBeTruthy();
    }
  });

  it("labels every credit check result", () => {
    const results: CreditCheckResult[] = ["pending", "passed", "failed"];
    for (const result of results) {
      expect(CREDIT_CHECK_LABELS[result]).toBeTruthy();
    }
  });
});

describe("badge classes", () => {
  it("returns a badge class for every lead status", () => {
    const statuses: LeadStatus[] = ["new", "contacted", "qualified", "disqualified"];
    for (const status of statuses) {
      expect(leadStatusBadgeClass(status)).toContain("ring-1");
    }
  });

  it("returns a badge class for every pipeline stage", () => {
    const stages: OpportunityStage[] = [
      "prospecting",
      "qualified",
      "proposal",
      "negotiation",
      "won",
      "lost",
    ];
    for (const stage of stages) {
      expect(opportunityStageBadgeClass(stage)).toContain("ring-1");
    }
  });

  it("returns a badge class for every order status", () => {
    const statuses: OrderStatus[] = ["draft", "confirmed", "fulfilled", "cancelled"];
    for (const status of statuses) {
      expect(orderStatusBadgeClass(status)).toContain("ring-1");
    }
  });

  it("returns a badge class for every credit check result", () => {
    const results: CreditCheckResult[] = ["pending", "passed", "failed"];
    for (const result of results) {
      expect(creditCheckBadgeClass(result)).toContain("ring-1");
    }
  });
});
