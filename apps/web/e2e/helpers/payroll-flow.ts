/*
 * In-page BFF helpers for payroll and HR operations.
 */

import { type Page } from "@playwright/test";

interface BffResponse<T = unknown> {
  data?: T;
  meta?: Record<string, number>;
  message?: string;
}

async function bff<T = unknown>(
  page: Page,
  url: string,
  init?: RequestInit,
): Promise<T> {
  return page.evaluate(async ([url, init]) => {
    const res = await fetch(url, {
      credentials: "include",
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers as Record<string, string>),
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`BFF ${url} failed: ${res.status} ${text}`);
    }
    return res.json() as Promise<T>;
  }, [url, init] as const);
}

function suffix(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export async function updatePayrollSettings(
  page: Page,
  settings: {
    pf_rate?: number;
    tax_rate?: number;
    rounding?: "nearest" | "up" | "down";
    ai_automation_enabled?: boolean;
    je_bridge_enabled?: boolean;
    default_currency?: string;
  },
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse>(page, "/api/v1/payroll/settings", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
  return res.data as Record<string, unknown>;
}

export async function getPayrollSettings(
  page: Page,
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse>(page, "/api/v1/payroll/settings");
  return res.data as Record<string, unknown>;
}

export async function hireEmployee(
  page: Page,
  opts: {
    firstName?: string;
    lastName?: string;
    jobTitle?: string;
    hireDate?: string;
    email?: string;
    monthlySalary?: string;
  },
): Promise<{ id: string; first_name: string; last_name: string }> {
  const s = suffix();
  const res = await bff<BffResponse>(page, "/api/v1/hr/employees", {
    method: "POST",
    body: JSON.stringify({
      first_name: opts.firstName ?? "E2E",
      last_name: opts.lastName ?? `Employee-${s}`,
      job_title: opts.jobTitle ?? "Engineer",
      hire_date: opts.hireDate ?? "2026-01-05",
      email: opts.email ?? `e2e-${s}@example.com`,
      monthly_salary: opts.monthlySalary ?? "5000.00",
    }),
  });
  return res.data as { id: string; first_name: string; last_name: string };
}

export async function createPayrollRun(
  page: Page,
  opts: { periodStart: string; periodEnd: string },
): Promise<{ id: string; status: string }> {
  const res = await bff<BffResponse>(page, "/api/v1/payroll/runs", {
    method: "POST",
    body: JSON.stringify({
      period_start: opts.periodStart,
      period_end: opts.periodEnd,
    }),
  });
  return res.data as { id: string; status: string };
}

export async function computePayrollRun(
  page: Page,
  runId: string,
): Promise<{
  run: Record<string, unknown>;
  entries: Record<string, unknown>[];
  skipped: Record<string, unknown>[];
}> {
  const res = await bff<BffResponse>(
    page,
    `/api/v1/payroll/runs/${runId}/compute`,
    { method: "POST" },
  );
  return res.data as {
    run: Record<string, unknown>;
    entries: Record<string, unknown>[];
    skipped: Record<string, unknown>[];
  };
}

export async function approvePayrollRun(
  page: Page,
  runId: string,
): Promise<{ id: string; status: string }> {
  const res = await bff<BffResponse>(
    page,
    `/api/v1/payroll/runs/${runId}/approve`,
    { method: "POST" },
  );
  return res.data as { id: string; status: string };
}

export async function tickPayrollBatch(
  page: Page,
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse>(page, "/api/v1/ai/payroll/tick", {
    method: "POST",
  });
  return (res.data ?? res) as Record<string, unknown>;
}

export async function getPayslipReviews(
  page: Page,
): Promise<Record<string, unknown>[]> {
  const res = await bff<BffResponse<Record<string, unknown>[]>>(
    page,
    "/api/v1/payroll/payslips/reviews",
  );
  return res.data ?? [];
}

export async function approvePayslipReview(
  page: Page,
  reviewId: string,
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse>(
    page,
    `/api/v1/payroll/payslips/reviews/${reviewId}/approve`,
    { method: "POST" },
  );
  return res.data as Record<string, unknown>;
}

export async function enableAiAutomation(
  page: Page,
): Promise<Record<string, unknown>> {
  return updatePayrollSettings(page, { ai_automation_enabled: true });
}

export async function listNotifications(
  page: Page,
): Promise<Record<string, unknown>[]> {
  const res = await bff<BffResponse<Record<string, unknown>[]>>(
    page,
    "/api/v1/notifications?page=1&page_size=50",
  );
  return res.data ?? [];
}
