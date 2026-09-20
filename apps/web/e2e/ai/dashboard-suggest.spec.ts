/*
 * AI journey: dashboard layout suggestion honest-status contract (BUG-AI-002).
 *
 * The e2e stack enables AI_DASHBOARD_SUGGEST_ENABLED (see docker-compose.e2e.yml)
 * and runs the deterministic MockProvider. The seeded default tenant has NO
 * widget interaction events, so Core's own threshold is not met and the honest
 * answer is always `insufficient_data` - the contract being asserted is that a
 * suggestion request NEVER returns a silent empty 200 (that was the bug):
 *
 *   1. the endpoint answers 200 with an explicit `status` field;
 *   2. with no telemetry it is `insufficient_data` and the current layout is
 *      returned untouched (no fabricated widgets, no reasoning invented);
 *   3. the response shape has the three fields the UI consumes.
 *
 * The `suggested` / `fallback` arms stay covered by unit tests: `suggested`
 * needs 50+ seeded events and `fallback` needs the provider disabled, neither
 * of which is reachable in a fixed-flag, mock-provider e2e stack.
 */

import { expect, type Page } from "@playwright/test";

import { test } from "../fixtures/auth";

interface BffResponse {
    status: string;
    suggested_layout: Array<{ id: string; cols: number; visible: boolean }>;
    reasoning: string;
    confidence: number;
}

async function bff<T>(page: Page, url: string, init?: RequestInit): Promise<T> {
    return page.evaluate(
        async ([url, init]) => {
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
            return res.json() as unknown as T;
        },
        [url, init] as const,
    );
}

test.describe("dashboard layout suggestion", () => {
    test("suggestion is never a silent success", async ({ workspace }) => {
        const { page } = workspace;

        // Read the caller's effective layout, then ask for a suggestion against it.
        const layout = await bff<{ layout: unknown[] }>(
            page,
            "/api/v1/dashboards/me",
        );

        const suggestion = await bff<BffResponse>(
            page,
            "/api/v1/ai/dashboards/suggest",
            {
                method: "POST",
                body: JSON.stringify({ current_layout: layout.layout }),
            },
        );

        // Explicit status - one of exactly the three honest outcomes.
        expect(["suggested", "insufficient_data", "fallback"]).toContain(
            suggestion.status,
        );

        // No telemetry in the e2e seed -> Core's threshold is not met.
        expect(suggestion.status).toBe("insufficient_data");
        // The current layout is returned untouched - never a fabricated widget.
        expect(suggestion.suggested_layout).toEqual(layout.layout);
        expect(typeof suggestion.reasoning).toBe("string");
        expect(suggestion.confidence).toBe(0);
    });
});
