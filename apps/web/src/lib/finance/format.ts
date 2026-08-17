const moneyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
});

/** Backend money is Decimal, serialized as a number or string — coerce defensively. */
export function formatMoney(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return String(value);
  return moneyFormatter.format(amount);
}

/** Coerce a Decimal value to a real number (0 for empty/invalid). */
export function toMoney(value: number | string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const amount = Number(value);
  return Number.isNaN(amount) ? 0 : amount;
}

/** Sum backend money values safely (avoids string concatenation). */
export function sumMoney(values: ReadonlyArray<number | string | null | undefined>): number {
  return values.reduce<number>((sum, value) => sum + toMoney(value), 0);
}

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateFormatter.format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateTimeFormatter.format(date);
}

export type AccountType = "asset" | "liability" | "equity" | "revenue" | "expense";

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  asset: "Asset",
  liability: "Liability",
  equity: "Equity",
  revenue: "Revenue",
  expense: "Expense",
};

export type EntryStatus = "draft" | "posted" | "voided";

export const ENTRY_STATUS_LABELS: Record<EntryStatus, string> = {
  draft: "Draft",
  posted: "Posted",
  voided: "Voided",
};

export type InvoiceStatus = "draft" | "issued" | "approved" | "paid" | "voided";

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  draft: "Draft",
  issued: "Issued",
  approved: "Approved",
  paid: "Paid",
  voided: "Voided",
};
