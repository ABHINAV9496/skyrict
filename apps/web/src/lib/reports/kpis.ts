/*
 * Pure mappers from report-run payloads to the five dashboard KPI cards.
 *
 * Every KPI is derived straight from a Core report-run result (the same rows
 * the workspace table displays) so a card value always reconciles exactly
 * with its source report. No client-side invention: a failing source report
 * produces an error card, never zeros.
 */

import type { ReportRunResult } from "@/lib/api/reports-api";
import { formatMoney, formatNumber } from "@/lib/erp/money";
import { firstDayOfMonthIso, toQueryString, todayIso } from "@/lib/reports/params";

export type KpiId =
  | "cash_received"
  | "ar_aging"
  | "pipeline_value"
  | "stock_alerts"
  | "headcount";

export interface DashboardKpiDef {
  id: KpiId;
  /** Report slug this KPI is sourced from (matches the Core seed catalog). */
  slug: string;
  label: string;
  /** Parameters used to run the source report. */
  params: () => Record<string, string>;
  /** Declared params on the source definition, for safe URL serialization. */
  declaredParams: string[];
  /** Base detail-page path for the source report. */
  href: string;
}

export const DASHBOARD_KPI_DEFS: DashboardKpiDef[] = [
  {
    id: "cash_received",
    slug: "cash_received",
    label: "Cash received",
    params: () => ({ from_date: firstDayOfMonthIso(), to_date: todayIso() }),
    declaredParams: ["from_date", "to_date"],
    href: "/erp/reports/cash_received",
  },
  {
    id: "ar_aging",
    slug: "ar_aging",
    label: "Open receivables",
    params: () => ({ as_of_date: todayIso() }),
    declaredParams: ["as_of_date"],
    href: "/erp/reports/ar_aging",
  },
  {
    id: "pipeline_value",
    slug: "pipeline_value_by_stage",
    label: "Pipeline value",
    params: () => ({}),
    declaredParams: [],
    href: "/erp/reports/pipeline_value_by_stage",
  },
  {
    id: "stock_alerts",
    slug: "stock_on_hand_vs_reorder",
    label: "Stock alerts",
    params: () => ({}),
    declaredParams: [],
    href: "/erp/reports/stock_on_hand_vs_reorder",
  },
  {
    id: "headcount",
    slug: "headcount_by_department",
    label: "Headcount",
    params: () => ({}),
    declaredParams: [],
    href: "/erp/reports/headcount_by_department",
  },
];

/** Deep link to the source report with the exact parameters the card ran with. */
export function kpiHref(def: DashboardKpiDef): string {
  return `${def.href}${toQueryString(def.params(), def.declaredParams)}`;
}

function sumColumnNumber(result: ReportRunResult, column: string): number {
  let total = 0;
  for (const row of result.rows) {
    const parsed = Number(row[column]);
    if (Number.isFinite(parsed)) total += parsed;
  }
  return total;
}

export class KpiSourceColumnError extends Error {
  constructor(column: string, slug: string) {
    super(
      `Report ${slug} result is missing the "${column}" column required for this KPI.`,
    );
    this.name = "KpiSourceColumnError";
  }
}

function requireColumn(result: ReportRunResult, id: KpiId, column: string): void {
  if (!result.columns.includes(column)) {
    throw new KpiSourceColumnError(column, id);
  }
}

export function deriveKpiValue(
  id: KpiId,
  result: ReportRunResult,
): { value: string; hint: string } {
  switch (id) {
    case "cash_received":
      requireColumn(result, id, "total_received");
      return {
        value: formatMoney(sumColumnNumber(result, "total_received")),
        hint: "This month to date",
      };
    case "ar_aging":
      requireColumn(result, id, "outstanding");
      return {
        value: formatMoney(sumColumnNumber(result, "outstanding")),
        hint: "Open invoices as of today",
      };
    case "pipeline_value":
      requireColumn(result, id, "pipeline_value");
      return {
        value: formatMoney(sumColumnNumber(result, "pipeline_value")),
        hint: "Open opportunities",
      };
    case "stock_alerts":
      return {
        value: formatNumber(result.rows.length),
        hint: "Items at or below reorder point",
      };
    case "headcount":
      requireColumn(result, id, "headcount");
      return {
        value: formatNumber(sumColumnNumber(result, "headcount")),
        hint: "Current (non-terminated) employees",
      };
  }
}