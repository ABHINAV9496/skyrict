"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { FiscalPeriod } from "@/lib/api/finance-api";
import { cn } from "@/lib/utils";

export type PeriodGranularity = "all" | "year" | "month";

export interface PeriodValue {
  granularity: PeriodGranularity;
  year: string;
  month: string;
}

/** Inclusive date range for the selected period (null = no constraint / all time). */
export interface PeriodRange {
  from: string | null;
  to: string | null;
  /** The period end date — useful for "balances as of" style cutoffs. */
  asOf: string;
}

const GRANULARITY_OPTIONS: { value: PeriodGranularity; label: string }[] = [
  { value: "all", label: "All" },
  { value: "year", label: "Year" },
  { value: "month", label: "Month" },
];

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

export function defaultPeriodValue(): PeriodValue {
  return {
    granularity: "all",
    year: String(new Date().getFullYear()),
    month: today().slice(0, 7),
  };
}

export function lastDayOfMonth(year: number, month: number): string {
  const day = new Date(year, month, 0).getDate();
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function resolvePeriodRange(value: PeriodValue): PeriodRange {
  if (value.granularity === "all") {
    return { from: null, to: null, asOf: today() };
  }
  if (value.granularity === "year") {
    const from = `${value.year}-01-01`;
    const to = `${value.year}-12-31`;
    return { from, to, asOf: to };
  }
  const [year, month] = value.month.split("-").map(Number);
  const from = `${year}-${String(month).padStart(2, "0")}-01`;
  const to = lastDayOfMonth(year, month);
  return { from, to, asOf: to };
}

export function formatMonthLabel(month: string): string {
  const [year, parsedMonth] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "short", year: "numeric" }).format(
    new Date(year, parsedMonth - 1, 1),
  );
}

/** Years covered by the given fiscal periods, plus the current year, newest first. */
export function periodYearOptions(periods: FiscalPeriod[]): string[] {
  const years = new Set<number>([new Date().getFullYear()]);
  for (const period of periods) {
    const start = Number(period.start_date.slice(0, 4));
    const end = Number(period.end_date.slice(0, 4));
    for (let year = start; year <= end; year++) years.add(year);
  }
  return [...years].sort((a, b) => b - a).map(String);
}

/** Months covered by the given fiscal periods, plus the current month, newest first. */
export function periodMonthOptions(periods: FiscalPeriod[]): string[] {
  const months = new Set<string>([today().slice(0, 7)]);
  for (const period of periods) {
    let cursor = period.start_date.slice(0, 7);
    const last = period.end_date.slice(0, 7);
    while (cursor <= last) {
      months.add(cursor);
      const [year, month] = cursor.split("-").map(Number);
      cursor = month === 12 ? `${year + 1}-01` : `${year}-${String(month + 1).padStart(2, "0")}`;
    }
  }
  return [...months].sort((a, b) => b.localeCompare(a));
}

interface PeriodSelectorProps {
  value: PeriodValue;
  onChange: (value: PeriodValue) => void;
  /** Fiscal periods used to build the year/month options. */
  periods?: FiscalPeriod[];
  label?: string;
}

export function PeriodSelector({
  value,
  onChange,
  periods = [],
  label = "Period",
}: PeriodSelectorProps) {
  const yearOptions = periodYearOptions(periods);
  const monthOptions = periodMonthOptions(periods);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label={label}
        className="inline-flex rounded-lg border border-border bg-card p-0.5"
      >
        {GRANULARITY_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            aria-pressed={value.granularity === option.value}
            onClick={() => onChange({ ...value, granularity: option.value })}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              value.granularity === option.value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
      {value.granularity === "year" ? (
        <Select value={value.year} onValueChange={(year) => onChange({ ...value, year })}>
          <SelectTrigger className="w-28" aria-label="Year">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {yearOptions.map((year) => (
              <SelectItem key={year} value={year}>
                {year}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
      {value.granularity === "month" ? (
        <Select value={value.month} onValueChange={(month) => onChange({ ...value, month })}>
          <SelectTrigger className="w-32" aria-label="Month">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {monthOptions.map((month) => (
              <SelectItem key={month} value={month}>
                {formatMonthLabel(month)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : null}
    </div>
  );
}
