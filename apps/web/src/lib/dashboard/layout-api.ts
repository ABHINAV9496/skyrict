/**
 * API client for the dashboard layout CRUD endpoints.
 *
 * Endpoints (core service):
 *   GET    /api/v1/dashboards/me            - read effective layout
 *   PUT    /api/v1/dashboards/me            - save user layout
 *   POST   /api/v1/dashboards/me/reset      - reset to tenant default
 *   POST   /api/v1/dashboards/me/events     - record widget interaction events
 *   POST   /api/v1/ai/dashboards/suggest    - AI layout suggestion (core proxy)
 */

import type { LayoutItem } from "@/components/dashboard/erp/widget-grid";
import { ApiError, fetchWithSession } from "@/lib/api/http";

export interface DashboardLayoutResponse {
    layout: LayoutItem[];
    updated_at: string | null;
}

export interface EventPayload {
    widget_id: string;
    event: "open" | "hide";
}

export type SuggestionStatus = "suggested" | "insufficient_data" | "fallback";

export interface SuggestionResponse {
    status: SuggestionStatus;
    suggested_layout: LayoutItem[];
    reasoning: string;
    confidence: number;
}

/**
 * Fetch the effective layout for the current user.
 * Returns user override if it exists, otherwise tenant default.
 */
export async function fetchLayout(): Promise<DashboardLayoutResponse> {
    const response = await fetchWithSession("/api/v1/dashboards/me", {
        headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
        console.warn(
            `Layout API returned ${response.status}: ${response.statusText}`,
        );
        throw new ApiError(
            response.status,
            `Failed to fetch layout: ${response.status}`,
        );
    }
    return response.json();
}

/**
 * Save the user's personal dashboard layout.
 */
export async function saveLayout(
    layout: LayoutItem[],
): Promise<DashboardLayoutResponse> {
    const response = await fetchWithSession("/api/v1/dashboards/me", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ layout }),
    });
    if (!response.ok) {
        throw new ApiError(
            response.status,
            `Failed to save layout: ${response.status}`,
        );
    }
    return response.json();
}

/**
 * Reset the user's layout to the tenant default.
 */
export async function resetLayout(): Promise<void> {
    const response = await fetchWithSession("/api/v1/dashboards/me/reset", {
        method: "POST",
    });
    if (!response.ok) {
        throw new ApiError(
            response.status,
            `Failed to reset layout: ${response.status}`,
        );
    }
}

/**
 * Record widget interaction events (batched).
 */
export async function recordEvents(events: EventPayload[]): Promise<void> {
    if (events.length === 0) return;
    const response = await fetchWithSession("/api/v1/dashboards/me/events", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events }),
    });
    if (!response.ok) {
        // Fire-and-forget: telemetry failure is non-fatal
        console.warn("Failed to record widget events:", response.status);
    }
}

/**
 * Request an AI layout suggestion based on widget telemetry.
 *
 * Routes through the core proxy (`/api/v1/ai/dashboards/suggest`), which
 * forwards to ai-agent. Returns an explicit status - never a silent success:
 * `suggested` (a new layout), `insufficient_data` (not enough telemetry), or
 * `fallback` (AI unavailable; keep the current layout).
 */
export async function suggestLayout(
    currentLayout: LayoutItem[],
): Promise<SuggestionResponse> {
    const response = await fetchWithSession("/api/v1/ai/dashboards/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_layout: currentLayout }),
    });
    if (!response.ok) {
        throw new ApiError(
            response.status,
            `Failed to suggest layout: ${response.status}`,
        );
    }
    return response.json();
}
