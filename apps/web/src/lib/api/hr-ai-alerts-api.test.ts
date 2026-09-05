import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getAnomalySummary,
  getEmployeeAnomalies,
  getEmployeeUtilization,
  getUtilizationSummary,
} from "@/lib/api/hr-api";

const httpFetch = vi.fn();

vi.mock("@/lib/api/http", () => ({
  apiFetch: (path: string, options?: RequestInit) => httpFetch(path, options),
  apiList: () => Promise.reject(new Error("not used in this suite")),
  apiPost: () => Promise.reject(new Error("not used in this suite")),
  apiFetchEnvelope: () => Promise.reject(new Error("not used in this suite")),
  buildQueryString: () => "",
}));

describe("HR AI alert clients", () => {
  beforeEach(() => {
    httpFetch.mockReset();
  });

  it("maps the utilization org envelope", async () => {
    httpFetch.mockResolvedValue({
      total_alerts: 3,
      by_type: { forfeit_risk: 2, negative_balance: 1 },
      by_severity: { medium: 3 },
      generated_at: "2026-09-02T04:00:00Z",
      narrative: "3 utilization alert(s) open.",
    });

    const summary = await getUtilizationSummary();

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/utilization", undefined);
    expect(summary).toEqual({
      totalAlerts: 3,
      byType: { forfeit_risk: 2, negative_balance: 1 },
      bySeverity: { medium: 3 },
      generatedAt: "2026-09-02T04:00:00Z",
      narrative: "3 utilization alert(s) open.",
    });
  });

  it("maps the per-employee utilization list", async () => {
    httpFetch.mockResolvedValue([
      {
        employee_id: "emp-1",
        employee_number: "E-001",
        name: "Jane Doe",
        department_name: "Engineering",
        alert_type: "forfeit_risk",
        severity: "medium",
        balance_days: 18,
        projected_forfeiture_days: 18,
        days_remaining_in_year: 55,
        leave_type: "annual",
        status: "open",
        evidence: { forfeit_window_days: 60 },
        created_at: "2026-09-02T03:00:00Z",
      },
    ]);

    const alerts = await getEmployeeUtilization("emp-1");

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/utilization/emp-1", undefined);
    expect(alerts).toEqual([
      {
        employeeId: "emp-1",
        employeeNumber: "E-001",
        name: "Jane Doe",
        departmentName: "Engineering",
        alertType: "forfeit_risk",
        severity: "medium",
        balanceDays: 18,
        projectedForfeitureDays: 18,
        daysRemainingInYear: 55,
        leaveType: "annual",
        status: "open",
        evidence: { forfeit_window_days: 60 },
        createdAt: "2026-09-02T03:00:00Z",
      },
    ]);
  });

  it("maps the anomaly org envelope", async () => {
    httpFetch.mockResolvedValue({
      total_anomalies: 2,
      by_type: { short_notice_monday_friday: 1, leave_overuse: 1 },
      by_severity: { high: 1, medium: 1 },
      generated_at: "2026-09-02T04:00:00Z",
      narrative: "2 open leave anomaly(-ies).",
    });

    const summary = await getAnomalySummary();

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/anomalies", undefined);
    expect(summary).toEqual({
      totalAnomalies: 2,
      byType: { short_notice_monday_friday: 1, leave_overuse: 1 },
      bySeverity: { high: 1, medium: 1 },
      generatedAt: "2026-09-02T04:00:00Z",
      narrative: "2 open leave anomaly(-ies).",
    });
  });

  it("maps the per-employee anomaly list", async () => {
    httpFetch.mockResolvedValue([
      {
        employee_id: "emp-2",
        employee_number: "E-002",
        name: "John Roe",
        department_name: "Engineering",
        anomaly_type: "leave_overuse",
        severity: "high",
        title: "Annual leave above team median",
        description: "Took 3x the team median annual leave days.",
        team_size: 6,
        evidence: { median_days: 2.0, taken_days: 6 },
        status: "open",
        created_at: "2026-09-02T02:00:00Z",
      },
    ]);

    const anomalies = await getEmployeeAnomalies("emp-2");

    expect(httpFetch).toHaveBeenCalledWith("/api/v1/ai/hr/alerts/anomalies/emp-2", undefined);
    expect(anomalies).toEqual([
      {
        employeeId: "emp-2",
        employeeNumber: "E-002",
        name: "John Roe",
        departmentName: "Engineering",
        anomalyType: "leave_overuse",
        severity: "high",
        title: "Annual leave above team median",
        description: "Took 3x the team median annual leave days.",
        teamSize: 6,
        evidence: { median_days: 2.0, taken_days: 6 },
        status: "open",
        createdAt: "2026-09-02T02:00:00Z",
      },
    ]);
  });

  it("returns empty lists for a null detail response", async () => {
    httpFetch.mockResolvedValue(null);
    await expect(getEmployeeUtilization("emp-x")).resolves.toEqual([]);
    await expect(getEmployeeAnomalies("emp-x")).resolves.toEqual([]);
  });
});