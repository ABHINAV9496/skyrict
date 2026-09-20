import { describe, expect, it } from "vitest";

import { firstDayOfMonthIso, todayIso } from "@/lib/reports/params";
import type { ReportRunResult } from "@/lib/api/reports-api";
import {
  DASHBOARD_KPI_DEFS,
  deriveKpiValue,
  kpiHref,
} from "@/lib/reports/kpis";

/** A minimal run-result factory matching Core's stringified cell rows. */
function run(
  columns: string[],
  rows: Record<string, string>[],
): ReportRunResult {
  return {
    columns,
    rows,
    truncated: false,
    period: "fixture",
    snapshot_id: "s_fixture",
    generated_at: "2026-09-06T12:00:00Z",
  };
}

describe("deriveKpiValue - reconciliation with source report runs", () => {
  it("cash_received sums total_received across the month rows", () => {
    const result = run(
      ["payment_date", "payment_method", "payment_count", "total_received"],
      [
        { payment_date: "2026-09-01", payment_method: "bank", payment_count: "3", total_received: "1250.00" },
        { payment_date: "2026-09-02", payment_method: "card", payment_count: "5", total_received: "840.50" },
        { payment_date: "2026-09-03", payment_method: "bank", payment_count: "2", total_received: "125" },
      ],
    );
    expect(deriveKpiValue("cash_received", result)).toEqual({
      value: "$2,215.50",
      hint: "This month to date",
    });
  });

  it("ar_aging sums the outstanding column (net of applied payments)", () => {
    const result = run(
      ["invoice_number", "invoice_date", "due_date", "total", "paid_total", "outstanding", "aging_bucket"],
      [
        { invoice_number: "INV-1", invoice_date: "2026-08-01", due_date: "2026-08-15", total: "5000.00", paid_total: "2000.00", outstanding: "3000.00", aging_bucket: "1-30" },
        { invoice_number: "INV-2", invoice_date: "2026-05-01", due_date: "2026-05-15", total: "1200.00", paid_total: "0.00", outstanding: "1200.00", aging_bucket: "90+" },
      ],
    );
    expect(deriveKpiValue("ar_aging", result)).toEqual({
      value: "$4,200.00",
      hint: "Open invoices as of today",
    });
  });

  it("pipeline_value sums open-stage opportunity value", () => {
    const result = run(
      ["stage", "opportunity_count", "pipeline_value"],
      [
        { stage: "proposal", opportunity_count: "4", pipeline_value: "48000.00" },
        { stage: "negotiation", opportunity_count: "2", pipeline_value: "27500.50" },
      ],
    );
    expect(deriveKpiValue("pipeline_value", result)).toEqual({
      value: "$75,500.50",
      hint: "Open opportunities",
    });
  });

  it("stock_alerts counts rows - one row per product at/below reorder", () => {
    const result = run(
      ["sku", "product_name", "qty_on_hand", "reorder_point", "gap_to_reorder"],
      [
        { sku: "SKU-1", product_name: "Widget", qty_on_hand: "2", reorder_point: "10", gap_to_reorder: "8" },
        { sku: "SKU-2", product_name: "Gadget", qty_on_hand: "9", reorder_point: "10", gap_to_reorder: "1" },
        { sku: "SKU-3", product_name: "Doodad", qty_on_hand: "0", reorder_point: "5", gap_to_reorder: "5" },
      ],
    );
    expect(deriveKpiValue("stock_alerts", result)).toEqual({
      value: "3",
      hint: "Items at or below reorder point",
    });
    expect(deriveKpiValue("stock_alerts", run([...result.columns], []))).toEqual({
      value: "0",
      hint: "Items at or below reorder point",
    });
  });

  it("headcount sums non-terminated employees per department", () => {
    const result = run(
      ["department_name", "headcount"],
      [
        { department_name: "Engineering", headcount: "12" },
        { department_name: "Sales", headcount: "8" },
        { department_name: "Operations", headcount: "5" },
      ],
    );
    expect(deriveKpiValue("headcount", result)).toEqual({
      value: "25",
      hint: "Current (non-terminated) employees",
    });
  });

  it("tolerates non-numeric cells without crashing", () => {
    const result = run(["stage", "pipeline_value"], [
      { stage: "proposal", pipeline_value: "n/a" },
    ]);
    expect(deriveKpiValue("pipeline_value", result).value).toBe("$0.00");
  });

  it("throws KpiSourceColumnError when a KPI's source column is missing (regression: stale ar_aging definition shows ₹0)", () => {
    // A stale ar_aging definition returns only the 4 legacy columns - no
    // `outstanding`. The card must surface an error instead of silently
    // summing a missing column to ₹0.
    const stale = run(
      ["invoice_number", "invoice_date", "due_date", "total"],
      [
        {
          invoice_number: "INV-0002",
          invoice_date: "2026-08-07",
          due_date: "2026-09-21",
          total: "18500.00",
        },
      ],
    );
    expect(() => deriveKpiValue("ar_aging", stale)).toThrow("outstanding");
  });

  it("throws KpiSourceColumnError for cash_received without total_received", () => {
    const stale = run(["payment_date"], []);
    expect(() => deriveKpiValue("cash_received", stale)).toThrow("total_received");
  });

  it("throws KpiSourceColumnError for pipeline_value without pipeline_value", () => {
    const stale = run(["stage"], []);
    expect(() => deriveKpiValue("pipeline_value", stale)).toThrow("pipeline_value");
  });

  it("throws KpiSourceColumnError for headcount without headcount", () => {
    const stale = run(["department_name"], []);
    expect(() => deriveKpiValue("headcount", stale)).toThrow("headcount");
  });
});

describe("DASHBOARD_KPI_DEFS", () => {
  it("declares five cards, each with a unique id and slug", () => {
    const ids = DASHBOARD_KPI_DEFS.map((def) => def.id);
    expect(ids).toEqual([
      "cash_received",
      "ar_aging",
      "pipeline_value",
      "stock_alerts",
      "headcount",
    ]);
  });

  it("sources cash received with the current month window", () => {
    const cash = DASHBOARD_KPI_DEFS.find((def) => def.id === "cash_received");
    expect(cash?.params()).toEqual({
      from_date: firstDayOfMonthIso(),
      to_date: todayIso(),
    });
  });

  it("deep links include the exact params the card ran with", () => {
    const cash = DASHBOARD_KPI_DEFS.find((def) => def.id === "cash_received");
    expect(kpiHref(cash!)).toBe(
      `/erp/reports/cash_received?from_date=${firstDayOfMonthIso()}&to_date=${todayIso()}`,
    );

    const pipeline = DASHBOARD_KPI_DEFS.find((def) => def.id === "pipeline_value");
    expect(kpiHref(pipeline!)).toBe("/erp/reports/pipeline_value_by_stage");
  });
});