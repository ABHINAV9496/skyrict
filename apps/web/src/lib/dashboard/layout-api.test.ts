import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/http";
import { suggestLayout } from "@/lib/dashboard/layout-api";
import type { LayoutItem } from "@/components/dashboard/erp/widget-grid";

const httpMocks = vi.hoisted(() => ({ fetchWithSession: vi.fn() }));

vi.mock("@/lib/api/http", async (importOriginal) => {
    const actual = await importOriginal<typeof import("@/lib/api/http")>();
    return {
        ...actual,
        fetchWithSession: httpMocks.fetchWithSession,
    };
});

const layout: LayoutItem[] = [
    { id: "ai_digest", order: 0, cols: 4, visible: true },
    { id: "erp_overview", order: 1, cols: 2, visible: true },
];

describe("suggestLayout", () => {
    beforeEach(() => {
        httpMocks.fetchWithSession.mockReset();
    });

    it("posts the current layout to the AI suggestion proxy", async () => {
        httpMocks.fetchWithSession.mockResolvedValue({
            ok: true,
            json: async () => ({
                status: "suggested",
                suggested_layout: [
                    { id: "ai_digest", order: 0, cols: 4, visible: true },
                    { id: "erp_overview", order: 1, cols: 2, visible: false },
                ],
                reasoning: "Digest is used daily; overview is ignored.",
                confidence: 0.7,
            }),
        });

        const result = await suggestLayout(layout);

        expect(httpMocks.fetchWithSession).toHaveBeenCalledWith(
            "/api/v1/ai/dashboards/suggest",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ current_layout: layout }),
            },
        );
        expect(result.status).toBe("suggested");
        expect(result.suggested_layout[1].visible).toBe(false);
    });

    it("surfaces insufficient_data without inventing a layout", async () => {
        httpMocks.fetchWithSession.mockResolvedValue({
            ok: true,
            json: async () => ({
                status: "insufficient_data",
                suggested_layout: layout,
                reasoning: "Not enough widget telemetry yet.",
                confidence: 0,
            }),
        });

        const result = await suggestLayout(layout);

        expect(result.status).toBe("insufficient_data");
        expect(result.suggested_layout).toEqual(layout);
    });

    it("returns fallback status when the AI is unavailable", async () => {
        httpMocks.fetchWithSession.mockResolvedValue({
            ok: true,
            json: async () => ({
                status: "fallback",
                suggested_layout: layout,
                reasoning:
                    "AI suggestion unavailable - showing current layout.",
                confidence: 0,
            }),
        });

        const result = await suggestLayout(layout);

        expect(result.status).toBe("fallback");
        expect(result.suggested_layout).toEqual(layout);
    });

    it("throws an ApiError on a failed response", async () => {
        httpMocks.fetchWithSession.mockResolvedValue({
            ok: false,
            status: 500,
        });

        await expect(suggestLayout(layout)).rejects.toBeInstanceOf(ApiError);
    });
});
