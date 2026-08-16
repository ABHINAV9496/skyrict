/**
 * Display helpers for API values. Money always arrives as a decimal *string*
 * (Pydantic serializes Decimal to text), so formatting goes straight to
 * Intl.NumberFormat — never coerced through Number() for display or math.
 */

const dateOnlyPattern = /^\d{4}-\d{2}-\d{2}$/;

function toDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Date-only strings parse as UTC midnight; anchoring them keeps the calendar
  // date stable regardless of the viewer's timezone.
  const date = dateOnlyPattern.test(value)
    ? new Date(`${value}T00:00:00Z`)
    : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const currencyFormatters = new Map<string, Intl.NumberFormat>();

/** Format a decimal-string or numeric amount as currency. Returns "—" for empty. */
export function formatMoney(
  amount: string | number | null | undefined,
  currency = "USD",
): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  let formatter = currencyFormatters.get(currency);
  if (!formatter) {
    formatter = new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
    });
    currencyFormatters.set(currency, formatter);
  }
  return formatter.format(amount as number);
}

/** Format a date-only or date-time string as a short calendar date. */
export function formatDate(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(dateOnlyPattern.test(value ?? "") ? { timeZone: "UTC" } : {}),
  }).format(date);
}

/** Format a date-only or date-time string with time. */
export function formatDateTime(value: string | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(dateOnlyPattern.test(value ?? "") ? { timeZone: "UTC" } : {}),
  }).format(date);
}

/** Format a decimal-string rate as a percent (e.g. "0.05" → "5%"). */
export function formatRate(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const rate = Number(value);
  if (!Number.isFinite(rate)) return "—";
  return new Intl.NumberFormat(undefined, {
    style: "percent",
    maximumFractionDigits: 2,
  }).format(rate);
}
