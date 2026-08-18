import { describe, expect, it } from "vitest";

import {
  isTerminalStage,
  leadActions,
  nextStages,
  orderActions,
  PIPELINE_STAGES,
} from "@/lib/erp/actions";

describe("leadActions", () => {
  it("allows qualify and disqualify for new leads", () => {
    expect(leadActions("new")).toEqual({ qualify: true, disqualify: true });
  });

  it("allows qualify and disqualify for contacted leads", () => {
    expect(leadActions("contacted")).toEqual({ qualify: true, disqualify: true });
  });

  it("is terminal for qualified leads", () => {
    expect(leadActions("qualified")).toEqual({ qualify: false, disqualify: false });
  });

  it("is terminal for disqualified leads", () => {
    expect(leadActions("disqualified")).toEqual({ qualify: false, disqualify: false });
  });
});

describe("pipeline stages", () => {
  it("orders the board columns", () => {
    expect(PIPELINE_STAGES).toEqual([
      "prospecting",
      "qualified",
      "proposal",
      "negotiation",
      "won",
      "lost",
    ]);
  });

  it("marks won and lost as terminal", () => {
    expect(isTerminalStage("won")).toBe(true);
    expect(isTerminalStage("lost")).toBe(true);
    expect(isTerminalStage("prospecting")).toBe(false);
    expect(isTerminalStage("negotiation")).toBe(false);
  });
});

describe("nextStages", () => {
  it("moves forward one stage at a time", () => {
    expect(nextStages("prospecting")).toEqual(["qualified"]);
    expect(nextStages("qualified")).toEqual(["proposal"]);
    expect(nextStages("proposal")).toEqual(["negotiation"]);
  });

  it("allows won or lost from negotiation only", () => {
    expect(nextStages("negotiation")).toEqual(["won", "lost"]);
  });

  it("returns no transitions from terminal stages", () => {
    expect(nextStages("won")).toEqual([]);
    expect(nextStages("lost")).toEqual([]);
  });
});

describe("orderActions", () => {
  it("allows confirm and cancel for drafts", () => {
    expect(orderActions("draft")).toEqual({ confirm: true, fulfil: false, cancel: true });
  });

  it("allows fulfil and cancel for confirmed orders", () => {
    expect(orderActions("confirmed")).toEqual({ confirm: false, fulfil: true, cancel: true });
  });

  it("is terminal for fulfilled orders", () => {
    expect(orderActions("fulfilled")).toEqual({
      confirm: false,
      fulfil: false,
      cancel: false,
    });
  });

  it("is terminal for cancelled orders", () => {
    expect(orderActions("cancelled")).toEqual({
      confirm: false,
      fulfil: false,
      cancel: false,
    });
  });
});
