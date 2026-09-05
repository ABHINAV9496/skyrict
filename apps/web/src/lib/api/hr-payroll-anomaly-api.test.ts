import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  disposePayrollAnomaly,
  getEmployeePayrollAnomalies,
  getPayrollAnomalySummary,
} from "@/lib/api/hr-api";

const httpFetch = vi.fn();

vi.mock("@/lib/api/http", () => ({
  apiFetch: (path: string, options?: RequestInit) => httpFetch(path, options),
  apiList: () => Promise.reject(new Error("not used in this suite")),
  apiPost: (path: string, body?: unknown) =>
    httpFetch(path, body).then((response: Response) =>
      response.json().then((json: { data?: unknown }) => json.data),
    ),
  apiFetchEnvelope: () => Promise.reject(new Error("not used in this suite")),
  buildQueryString: () => "",
  fetchWithSession: (path: string, options?: RequestInit) => httpFetch(path, options),
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

describe("HR AI payroll anomaly clients", () => {
  beforeEach(() => {
    httpFetch.mockReset();
  });

  it("maps the L1 org feed", async () => {
    httpFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: {
            total_anomalies: 2,
            open_anomalies: 2,
            by_type: { ghost_employee: 1, duplicate_account: 1 },
            by_severity: { critical: 1, medium: 1 },
            generated_at: "2026-09-02T04:00:00Z",
            narrative: "1 critical payroll finding in the latest run.",
          },
        }),
    } as Response);

    const summary = await getPayrollAnomalySummary();

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/payroll", {});
    expect(summary).toEqual({
      totalAnomalies: 2,
      openAnomalies: 2,
      byType: { ghost_employee: 1, duplicate_account: 1 },
      bySeverity: { critical: 1, medium: 1 },
      generatedAt: "2026-09-02T04:00:00Z",
      narrative: "1 critical payroll finding in the latest run.",
    });
  });

  it("maps the L2 per-employee findings", async () => {
    httpFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: [
            {
              anomaly_id: "aaa-1",
              run_id: "run-9",
              run_code: "PR-2026-04",
              period_start: "2026-09-01",
              period_end: "2026-09-15",
              employee_id: "emp-1",
              employee_number: "E-001",
              name: "Jane Doe",
              department_name: "Engineering",
              anomaly_type: "ghost_employee",
              severity: "critical",
              title: "Pay run pays a terminated employee",
              description: "EMP-0014 was terminated but still appears unpaid",
              evidence: { detail: "terminated_at" },
              status: "open",
              acknowledged_by: null,
              acknowledged_at: null,
              created_at: "2026-09-02T04:00:00Z",
            },
          ],
        }),
    } as Response);

    const findings = await getEmployeePayrollAnomalies("emp-1");

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/payroll/emp-1", {});
    expect(findings).toEqual([
      {
        anomalyId: "aaa-1",
        runId: "run-9",
        runCode: "PR-2026-04",
        periodStart: "2026-09-01",
        periodEnd: "2026-09-15",
        employeeId: "emp-1",
        employeeNumber: "E-001",
        name: "Jane Doe",
        departmentName: "Engineering",
        anomalyType: "ghost_employee",
        severity: "critical",
        title: "Pay run pays a terminated employee",
        description: "EMP-0014 was terminated but still appears unpaid",
        evidence: { detail: "terminated_at" },
        status: "open",
        acknowledgedAt: null,
        createdAt: "2026-09-02T04:00:00Z",
      },
    ]);
  });

  it("throws a readable error when the L2 view is denied", async () => {
    httpFetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: () =>
        Promise.resolve({
          data: { detail: "erp.hr.ai.individual required for the individual view" },
        }),
    } as Response);

    await expect(getEmployeePayrollAnomalies("emp-1")).rejects.toThrow(
      /erp\.hr\.ai\.individual required/,
    );
  });

  it("POSTs a disposition and maps the updated finding", async () => {
    httpFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: {
            anomaly_id: "aaa-1",
            run_id: "run-9",
            run_code: "PR-2026-04",
            period_start: "2026-09-01",
            period_end: "2026-09-15",
            employee_id: "emp-1",
            employee_number: "E-001",
            name: "Jane Doe",
            department_name: "Engineering",
            anomaly_type: "ghost_employee",
            severity: "critical",
            title: "Pay run pays a terminated employee",
            description: "EMP-0014 was terminated but still appears unpaid",
            evidence: {},
            status: "acknowledged",
            acknowledged_by: "user-9",
            acknowledged_at: "2026-09-02T04:05:00Z",
            created_at: "2026-09-02T04:00:00Z",
          },
        }),
    } as Response);

    const finding = await disposePayrollAnomaly("aaa-1", "acknowledged");

    expect(httpFetch).toHaveBeenCalledWith(
      "/api/v1/ai/hr/alerts/payroll/aaa-1/disposition",
      { status: "acknowledged" },
    );
    expect(finding.status).toBe("acknowledged");
    expect(finding.acknowledgedAt).toBe("2026-09-02T04:05:00Z");
  });
});