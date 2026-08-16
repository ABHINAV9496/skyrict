import type { AccountType } from "@/lib/finance/format";

/**
 * Statement section identifiers derived from account code ranges.
 * Follows NetSuite/Sage/Odoo conventions for small ERP usage.
 */
export type StatementSection =
  | "current_asset"
  | "fixed_asset"
  | "other_asset"
  | "current_liability"
  | "long_term_liability"
  | "equity"
  | "revenue"
  | "other_income"
  | "cogs"
  | "operating_expense"
  | "other_expense";

type RangeRule = {
  min: number;
  max: number;
  section: StatementSection;
};

/**
 * Code ranges mapped to statement sections.
 * Rules are tested top-to-bottom; first match wins.
 */
const ASSET_RULES: RangeRule[] = [
  { min: 1000, max: 1099, section: "current_asset" },
  { min: 1100, max: 1199, section: "fixed_asset" },
  { min: 1200, max: 1999, section: "other_asset" },
];

const LIABILITY_RULES: RangeRule[] = [
  { min: 2000, max: 2099, section: "current_liability" },
  { min: 2100, max: 2999, section: "long_term_liability" },
];

const EQUITY_RULES: RangeRule[] = [
  { min: 3000, max: 3999, section: "equity" },
];

const REVENUE_RULES: RangeRule[] = [
  { min: 4000, max: 4099, section: "revenue" },
  { min: 4100, max: 4999, section: "other_income" },
];

const EXPENSE_RULES: RangeRule[] = [
  { min: 5000, max: 5099, section: "cogs" },
  { min: 6000, max: 6999, section: "operating_expense" },
  { min: 7000, max: 9999, section: "other_expense" },
];

const RULES_BY_TYPE: Record<AccountType, RangeRule[]> = {
  asset: ASSET_RULES,
  liability: LIABILITY_RULES,
  equity: EQUITY_RULES,
  revenue: REVENUE_RULES,
  expense: EXPENSE_RULES,
};

function matchCode(code: string, rules: RangeRule[]): StatementSection | null {
  const num = Number(code);
  if (Number.isNaN(num)) return null;
  for (const rule of rules) {
    if (num >= rule.min && num <= rule.max) return rule.section;
  }
  return null;
}

/**
 * Classify an account into a statement section based on its code and type.
 * Falls back to the type's "default" section when the code doesn't match any range.
 */
export function classifyAccount(
  code: string,
  accountType: AccountType,
): StatementSection {
  const rules = RULES_BY_TYPE[accountType];
  const result = matchCode(code, rules);
  if (result) return result;

  // Fallback: map each account type to its most common section
  const defaults: Record<AccountType, StatementSection> = {
    asset: "current_asset",
    liability: "current_liability",
    equity: "equity",
    revenue: "revenue",
    expense: "operating_expense",
  };
  return defaults[accountType];
}

export const SECTION_LABELS: Record<StatementSection, string> = {
  current_asset: "Current Assets",
  fixed_asset: "Fixed Assets",
  other_asset: "Other Assets",
  current_liability: "Current Liabilities",
  long_term_liability: "Long-term Liabilities",
  equity: "Equity",
  revenue: "Revenue",
  other_income: "Other Income",
  cogs: "Cost of Goods Sold",
  operating_expense: "Operating Expenses",
  other_expense: "Other Expenses",
};

/**
 * Sort order for sections within the Balance Sheet and P&L.
 * Lower number = appears first.
 */
export const BS_SECTION_ORDER: Record<StatementSection, number> = {
  current_asset: 0,
  fixed_asset: 1,
  other_asset: 2,
  current_liability: 10,
  long_term_liability: 11,
  equity: 20,
  // Unused in BS but required by type:
  revenue: 90,
  other_income: 91,
  cogs: 92,
  operating_expense: 93,
  other_expense: 94,
};

export const PNL_SECTION_ORDER: Record<StatementSection, number> = {
  revenue: 0,
  cogs: 10,
  operating_expense: 20,
  other_income: 30,
  other_expense: 31,
  // Unused in P&L but required by type:
  current_asset: 90,
  fixed_asset: 91,
  other_asset: 92,
  current_liability: 93,
  long_term_liability: 94,
  equity: 95,
};

/**
 * Sort order for account types on the Trial Balance.
 */
export const TB_TYPE_ORDER: Record<AccountType, number> = {
  asset: 0,
  liability: 1,
  equity: 2,
  revenue: 3,
  expense: 4,
};

/**
 * Recommended code range hint for the account creation form.
 */
export const CODE_RANGE_HINTS: { range: string; label: string }[] = [
  { range: "1000–1099", label: "Current Assets" },
  { range: "1100–1199", label: "Fixed Assets" },
  { range: "2000–2099", label: "Current Liabilities" },
  { range: "2100+", label: "Long-term Liabilities" },
  { range: "3000–3999", label: "Equity" },
  { range: "4000–4099", label: "Revenue" },
  { range: "5000–5099", label: "Cost of Goods Sold" },
  { range: "6000+", label: "Operating Expenses" },
];
