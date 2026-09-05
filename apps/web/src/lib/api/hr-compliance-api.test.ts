import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getComplianceSummary,
  getEmployeeComplianceFindings,
  setComplianceStatus,
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

describe("HR AI compliance clients", () => {
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
            total_findings: 3,
            open_findings: 3,
            by_type: {
              document_expiry: 1,
              training_overdue: 1,
              contract_missing_field: 1,
            },
            by_severity: { high: 1, medium: 2 },
            generated_at: "2026-09-02T04:00:00Z",
            narrative: "3 open compliance finding(-ies)",
          },
        }),
    } as Response);

    const summary = await getComplianceSummary();

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/compliance", {});
    expect(summary).toEqual({
      totalFindings: 3,
      openFindings: 3,
      byType: {
        document_expiry: 1,
        training_overdue: 1,
        contract_missing_field: 1,
      },
      bySeverity: { high: 1, medium: 2 },
      generatedAt: "2026-09-02T04:00:00Z",
      narrative: "3 open compliance finding(-ies)",
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
              check_id: "ccc-1",
              employee_id: "emp-1",
              employee_number: "E-001",
              name: "Jane Doe",
              department_name: "Engineering",
              check_type: "document_expiry",
              severity: "high",
              owner_rule: "compliance_officer",
              title: "Identity document expiring",
              description: "Visa document has expired (5 day(s) past due).",
              evidence: { doc_type: "visa", days_left: -5 },
              status: "open",
              owner_user_id: null,
              created_at: "2026-09-02T04:00:00Z",
            },
          ],
        }),
    } as Response);

    const findings = await getEmployeeComplianceFindings("emp-1");

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/compliance/emp-1", {});
    expect(findings).toEqual([
      {
        checkId: "ccc-1",
        employeeId: "emp-1",
        employeeNumber: "E-001",
        name: "Jane Doe",
        departmentName: "Engineering",
        checkType: "document_expiry",
        severity: "high",
        ownerRule: "compliance_officer",
        title: "Identity document expiring",
        description: "Visa document has expired (5 day(s) past due).",
        evidence: { doc_type: "visa", days_left: -5 },
        status: "open",
        ownerUserId: null,
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

    await expect(getEmployeeComplianceFindings("emp-1")).rejects.toThrow(
      /erp\.hr\.ai\.individual required/,
    );
  });

  it("POSTs a status update and maps the updated finding", async () => {
    httpFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: {
            check_id: "ccc-1",
            employee_id: "emp-1",
            employee_number: "E-001",
            name: "Jane Doe",
            department_name: "Engineering",
            check_type: "document_expiry",
            severity: "high",
            owner_rule: "compliance_officer",
            title: "Identity document expiring",
            description: "Visa document has expired (5 day(s) past due).",
            evidence: {},
            status: "acknowledged",
            owner_user_id: "user-9",
            created_at: "2026-09-02T04:00:00Z",
          },
        }),
    } as Response);

    const finding = await setComplianceStatus("ccc-1", "acknowledged");

    expect(httpFetch).toHaveBeenCalledWith(
      "/api/v1/ai/hr/alerts/compliance/ccc-1/status",
      { status: "acknowledged" },
    );
    expect(finding.status).toBe("acknowledged");
    expect(finding.ownerUserId).toBe("user-9");
  });
});
