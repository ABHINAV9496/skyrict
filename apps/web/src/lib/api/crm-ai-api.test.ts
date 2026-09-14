import { beforeEach, describe, expect, it, vi } from "vitest";

import {
    dismissCrmAnomaly,
    listCrmAnomalies,
    resolveCrmAnomaly,
} from "@/lib/api/crm-ai-api";

const httpMock = vi.fn<(path: string, options?: RequestInit) => Promise<unknown>>();

/**
 * Simulate the real http helpers: `apiFetchBody`/`apiPostBody` return the
 * whole response body - for these bare-endpoint CRM AI calls that is the
 * array or item itself, without an envelope. This mirrors lib/api/http.ts.
 */
vi.mock("@/lib/api/http", () => ({
    apiFetchBody: async (_path: string, _options: RequestInit = {}) => {
        const result = await httpMock(_path, _options);
        return result;
    },
    apiPostBody: async (_path: string, _options?: object) => {
        const result = await httpMock(_path, {
            method: "POST",
            body: JSON.stringify(_options ?? {}),
        });
        return result;
    },
}));

const anomaly = {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    opportunity_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    rule_id: "stage_stall",
    severity: "critical",
    status: "open",
    title: "Deal stuck",
    description: "No movement for 45 days.",
    context: { days_in_stage: 45 },
    detected_at: "2026-09-11T12:00:00Z",
};

describe("crm anomaly inbox endpoints", () => {
    beforeEach(() => {
        httpMock.mockReset();
    });

    it("lists open anomalies from the CRM AI proxy", async () => {
        httpMock.mockResolvedValue([anomaly]);

        const result = await listCrmAnomalies();

        expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/crm/anomalies", {});
        expect(result).toEqual([anomaly]);
    });

    it("resolves an anomaly via the resolve endpoint", async () => {
        httpMock.mockResolvedValue({ ...anomaly, status: "resolved" });

        const result = await resolveCrmAnomaly(anomaly.id);

        expect(httpMock).toHaveBeenCalledWith(
            `/api/v1/ai/crm/anomalies/${anomaly.id}/resolve`,
            { method: "POST", body: "{}" },
        );
        expect(result.status).toBe("resolved");
    });

    it("dismisses an anomaly via the dismiss endpoint", async () => {
        httpMock.mockResolvedValue({ ...anomaly, status: "dismissed" });

        const result = await dismissCrmAnomaly(anomaly.id);

        expect(httpMock).toHaveBeenCalledWith(
            `/api/v1/ai/crm/anomalies/${anomaly.id}/dismiss`,
            { method: "POST", body: "{}" },
        );
        expect(result.status).toBe("dismissed");
    });
});