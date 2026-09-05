import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  acknowledgeAttrition,
  getAttrition,
} from "@/lib/api/hr-api";

const httpFetch = vi.fn();

vi.mock("@/lib/api/http", () => ({
  apiFetch: (path: string, options?: RequestInit) => httpFetch(path, options),
  apiList: () => Promise.reject(new Error("not used in this suite")),
  apiPost: (path: string, body?: unknown) => httpFetch(path, body),
  apiFetchEnvelope: () => Promise.reject(new Error("not used in this suite")),
  buildQueryString: () => "",
  fetchWithSession: (path: string, options?: RequestInit) => httpFetch(path, options),
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));

describe("HR AI attrition clients", () => {
  beforeEach(() => {
    httpFetch.mockReset();
  });

  it("maps the L2 detail view for individual holders", async () => {
    httpFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: {
            generated_at: "2026-09-02T04:00:00Z",
            model_version: "hr_attrition_risk_v1",
            employees: [
              {
                employee_id: "emp-1",
                employee_number: "E-001",
                name: "Jane Doe",
                department_name: "Engineering",
                risk_band: "high",
                score: 0.82,
                confidence: 0.91,
                factors: [{ feature: "tenure", contribution: 0.4, direction: "up" }],
                acknowledged: false,
                acknowledged_at: null,
              },
            ],
          },
        }),
    } as Response);

    const view = await getAttrition();

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/attrition", {});
    expect(view.mode).toBe("detail");
    if (view.mode === "detail") {
      expect(view.modelVersion).toBe("hr_attrition_risk_v1");
      expect(view.generatedAt).toBe("2026-09-02T04:00:00Z");
      expect(view.employees).toEqual([
        {
          employeeId: "emp-1",
          employeeNumber: "E-001",
          name: "Jane Doe",
          departmentName: "Engineering",
          riskBand: "high",
          score: 0.82,
          confidence: 0.91,
          factors: [{ feature: "tenure", contribution: 0.4, direction: "up" }],
          acknowledged: false,
          acknowledgedAt: null,
        },
      ]);
    }
  });

  it("surfaces the L1 summary from the 403 body for non-individual callers", async () => {
    httpFetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: () =>
        Promise.resolve({
          data: {
            generated_at: "2026-09-02T04:00:00Z",
            model_version: "hr_attrition_risk_v1",
            high_risk_count: 2,
            medium_risk_count: 1,
            low_risk_count: 5,
            top_risk_departments: [
              {
                department_name: "Engineering",
                high_risk_count: 2,
                total_scores: 3,
                average_risk: 0.7,
              },
            ],
            narrative: "2 employee(s) at high attrition risk.",
          },
        }),
    } as Response);

    const view = await getAttrition();

    expect(view.mode).toBe("summary");
    if (view.mode === "summary") {
      expect(view.summary).toEqual({
        generatedAt: "2026-09-02T04:00:00Z",
        modelVersion: "hr_attrition_risk_v1",
        highRiskCount: 2,
        mediumRiskCount: 1,
        lowRiskCount: 5,
        topRiskDepartments: [
          { departmentName: "Engineering", highRiskCount: 2, totalScores: 3, averageRisk: 0.7 },
        ],
        narrative: "2 employee(s) at high attrition risk.",
      });
    }
  });

  it("throws a readable error when a 403 has no usable body", async () => {
    httpFetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: "Missing required permission: erp.ai.invoke" }),
    } as Response);

    await expect(getAttrition()).rejects.toThrow(/erp\.hr\.ai\.individual/);
  });

  it("POSTs the acknowledgement for the employee", async () => {
    httpFetch.mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ data: {} }) });

    await acknowledgeAttrition("emp-1");

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/attrition/emp-1/acknowledge", {});
  });
});
