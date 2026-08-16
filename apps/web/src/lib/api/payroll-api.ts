/**
 * Payroll API client (settings, runs, entries, compensation).
 *
 * Mirrors identity-api.ts: calls go through the same-origin /api/v1/* BFF
 * proxy, payloads are mapped from snake_case over the wire to camelCase here,
 * and every failure surfaces an `ApiError` the UI can render inline.
 */

import { ApiError, apiFetch, apiList, apiPost, buildQueryString, type Paginated } from "@/lib/api/http";

export type PayrollRunStatus = "draft" | "computed" | "approved" | "paid" | "void";

export type PayrollRounding = "nearest" | "up" | "down";

export interface Money {
  amount: string;
  currency: string;
}

export interface PayrollSettings {
  tenantId: string;
  defaultCurrency: string;
  pfRate: string;
  taxRate: string;
  rounding: PayrollRounding;
}

export interface PayrollRun {
  id: string;
  runCode: string;
  periodStart: string;
  periodEnd: string;
  status: PayrollRunStatus;
  totalGross: Money | null;
  totalNet: Money | null;
  computedBy: string | null;
  approvedBy: string | null;
  paidBy: string | null;
  computedAt: string | null;
  approvedAt: string | null;
  paidAt: string | null;
  voidReason: string | null;
  skippedEmployees: SkippedEmployee[];
  createdAt: string;
}

export interface SkippedEmployee {
  employeeId: string;
  reason: string;
}

export interface PayrollEntry {
  id: string;
  employeeId: string;
  baseSalary: Money;
  payDays: number;
  gross: Money;
  deductions: Money;
  net: Money;
  adjustments: Record<string, unknown> | null;
  createdAt: string;
}

export interface RunComputeResult {
  run: PayrollRun;
  entries: PayrollEntry[];
  skipped: SkippedEmployee[];
}

export interface Compensation {
  id: string;
  employeeId: string;
  monthlySalary: Money;
  effectiveFrom: string;
  isActive: boolean;
  createdAt: string;
}

interface MoneyPayload {
  amount?: unknown;
  currency?: unknown;
}

interface PayrollSettingsPayload {
  tenant_id?: unknown;
  default_currency?: unknown;
  pf_rate?: unknown;
  tax_rate?: unknown;
  rounding?: unknown;
}

interface PayrollRunPayload {
  id?: unknown;
  run_code?: unknown;
  period_start?: unknown;
  period_end?: unknown;
  status?: unknown;
  total_gross?: MoneyPayload | null;
  total_net?: MoneyPayload | null;
  computed_by?: unknown;
  approved_by?: unknown;
  paid_by?: unknown;
  computed_at?: unknown;
  approved_at?: unknown;
  paid_at?: unknown;
  void_reason?: unknown;
  skipped_employees?: unknown;
  created_at?: unknown;
}

interface PayrollEntryPayload {
  id?: unknown;
  employee_id?: unknown;
  base_salary?: MoneyPayload | null;
  pay_days?: unknown;
  gross?: MoneyPayload | null;
  deductions?: MoneyPayload | null;
  net?: MoneyPayload | null;
  adjustments?: unknown;
  created_at?: unknown;
}

interface CompensationPayload {
  id?: unknown;
  employee_id?: unknown;
  monthly_salary?: MoneyPayload | null;
  effective_from?: unknown;
  is_active?: unknown;
  created_at?: unknown;
}

function mapMoney(payload: MoneyPayload | null | undefined): Money | null {
  if (!payload) return null;
  return {
    amount: String(payload.amount ?? ""),
    currency: String(payload.currency ?? "USD"),
  };
}

function mapPayrollSettings(payload: PayrollSettingsPayload | null): PayrollSettings | null {
  if (!payload) return null;
  return {
    tenantId: String(payload.tenant_id ?? ""),
    defaultCurrency: String(payload.default_currency ?? "USD"),
    pfRate: String(payload.pf_rate ?? "0"),
    taxRate: String(payload.tax_rate ?? "0"),
    rounding: String(payload.rounding ?? "nearest") as PayrollRounding,
  };
}

function mapSkippedEmployees(value: unknown): SkippedEmployee[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => ({
    employeeId: String((item as { employee_id?: unknown })?.employee_id ?? ""),
    reason: String((item as { reason?: unknown })?.reason ?? ""),
  }));
}

function mapPayrollRun(payload: PayrollRunPayload): PayrollRun {
  return {
    id: String(payload.id ?? ""),
    runCode: String(payload.run_code ?? ""),
    periodStart: String(payload.period_start ?? ""),
    periodEnd: String(payload.period_end ?? ""),
    status: String(payload.status ?? "draft") as PayrollRunStatus,
    totalGross: mapMoney(payload.total_gross),
    totalNet: mapMoney(payload.total_net),
    computedBy: typeof payload.computed_by === "string" ? payload.computed_by : null,
    approvedBy: typeof payload.approved_by === "string" ? payload.approved_by : null,
    paidBy: typeof payload.paid_by === "string" ? payload.paid_by : null,
    computedAt: typeof payload.computed_at === "string" ? payload.computed_at : null,
    approvedAt: typeof payload.approved_at === "string" ? payload.approved_at : null,
    paidAt: typeof payload.paid_at === "string" ? payload.paid_at : null,
    voidReason: typeof payload.void_reason === "string" ? payload.void_reason : null,
    skippedEmployees: mapSkippedEmployees(payload.skipped_employees),
    createdAt: String(payload.created_at ?? ""),
  };
}

function mapPayrollEntry(payload: PayrollEntryPayload): PayrollEntry {
  return {
    id: String(payload.id ?? ""),
    employeeId: String(payload.employee_id ?? ""),
    baseSalary: mapMoney(payload.base_salary) ?? { amount: "0", currency: "USD" },
    payDays: typeof payload.pay_days === "number" ? payload.pay_days : 0,
    gross: mapMoney(payload.gross) ?? { amount: "0", currency: "USD" },
    deductions: mapMoney(payload.deductions) ?? { amount: "0", currency: "USD" },
    net: mapMoney(payload.net) ?? { amount: "0", currency: "USD" },
    adjustments:
      payload.adjustments !== null && typeof payload.adjustments === "object"
        ? (payload.adjustments as Record<string, unknown>)
        : null,
    createdAt: String(payload.created_at ?? ""),
  };
}

function mapCompensation(payload: CompensationPayload): Compensation {
  return {
    id: String(payload.id ?? ""),
    employeeId: String(payload.employee_id ?? ""),
    monthlySalary: mapMoney(payload.monthly_salary) ?? { amount: "0", currency: "USD" },
    effectiveFrom: String(payload.effective_from ?? ""),
    isActive: payload.is_active !== false,
    createdAt: String(payload.created_at ?? ""),
  };
}

export async function getPayrollSettings(): Promise<PayrollSettings | null> {
  const raw = await apiFetch<PayrollSettingsPayload | null>("/api/v1/payroll/settings");
  return mapPayrollSettings(raw ?? null);
}

export async function updatePayrollSettings(input: {
  defaultCurrency?: string;
  pfRate?: string;
  taxRate?: string;
  rounding?: PayrollRounding;
}): Promise<PayrollSettings> {
  const raw = await apiFetch<PayrollSettingsPayload>("/api/v1/payroll/settings", {
    method: "PUT",
    body: JSON.stringify({
      default_currency: input.defaultCurrency,
      pf_rate: input.pfRate,
      tax_rate: input.taxRate,
      rounding: input.rounding,
    }),
  });
  const settings = mapPayrollSettings(raw ?? null);
  if (!settings) throw new ApiError(502, "Settings update returned an empty response.");
  return settings;
}

export async function createPayrollRun(input: {
  periodStart: string;
  periodEnd: string;
}): Promise<PayrollRun> {
  const raw = await apiPost<PayrollRunPayload>("/api/v1/payroll/runs", {
    period_start: input.periodStart,
    period_end: input.periodEnd,
  });
  return mapPayrollRun(raw ?? {});
}

export async function listPayrollRuns(input: {
  page?: number;
  pageSize?: number;
  status?: PayrollRunStatus;
} = {}): Promise<Paginated<PayrollRun>> {
  const result = await apiList<PayrollRunPayload>("/api/v1/payroll/runs", {
    page: input.page,
    pageSize: input.pageSize,
    query: { status: input.status },
  });
  return { items: result.items.map(mapPayrollRun), meta: result.meta };
}

export async function getPayrollRun(runId: string): Promise<PayrollRun> {
  const raw = await apiFetch<PayrollRunPayload>(`/api/v1/payroll/runs/${runId}`);
  return mapPayrollRun(raw ?? {});
}

export async function computePayrollRun(runId: string): Promise<RunComputeResult> {
  const raw = await apiPost<{
    run?: PayrollRunPayload;
    entries?: PayrollEntryPayload[];
    skipped?: unknown;
  }>(`/api/v1/payroll/runs/${runId}/compute`, {});
  return {
    run: mapPayrollRun(raw?.run ?? {}),
    entries: Array.isArray(raw?.entries) ? raw.entries.map(mapPayrollEntry) : [],
    skipped: mapSkippedEmployees(raw?.skipped),
  };
}

export async function approvePayrollRun(runId: string): Promise<PayrollRun> {
  const raw = await apiPost<PayrollRunPayload>(
    `/api/v1/payroll/runs/${runId}/approve`,
    {},
  );
  return mapPayrollRun(raw ?? {});
}

export async function markPayrollRunPaid(runId: string): Promise<PayrollRun> {
  const raw = await apiPost<PayrollRunPayload>(`/api/v1/payroll/runs/${runId}/pay`, {});
  return mapPayrollRun(raw ?? {});
}

export async function voidPayrollRun(runId: string): Promise<PayrollRun> {
  const raw = await apiPost<PayrollRunPayload>(`/api/v1/payroll/runs/${runId}/void`, {});
  return mapPayrollRun(raw ?? {});
}

export async function listRunEntries(
  runId: string,
  employeeId?: string,
): Promise<PayrollEntry[]> {
  const items = await apiFetch<PayrollEntryPayload[]>(
    `/api/v1/payroll/runs/${runId}/entries${buildQueryString({ employee_id: employeeId })}`,
  );
  return (items ?? []).map(mapPayrollEntry);
}

export async function listCompensation(employeeId: string): Promise<Compensation[]> {
  const items = await apiFetch<CompensationPayload[]>(
    `/api/v1/payroll/compensation?employee_id=${encodeURIComponent(employeeId)}`,
  );
  return (items ?? []).map(mapCompensation);
}

export async function createCompensationChange(input: {
  employeeId: string;
  effectiveFrom: string;
  monthlySalary: string;
  currency?: string;
}): Promise<Compensation> {
  const raw = await apiPost<CompensationPayload>("/api/v1/payroll/compensation", {
    employee_id: input.employeeId,
    effective_from: input.effectiveFrom,
    monthly_salary: input.monthlySalary,
    currency: input.currency,
  });
  return mapCompensation(raw ?? {});
}
