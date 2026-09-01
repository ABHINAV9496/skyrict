/**
 * API client for the dashboard layout CRUD endpoints.
 *
 * Endpoints (core service):
 *   GET    /api/v1/dashboards/me          — read effective layout
 *   PUT    /api/v1/dashboards/me          — save user layout
 *   POST   /api/v1/dashboards/me/reset    — reset to tenant default
 *   POST   /api/v1/dashboards/me/events   — record widget interaction events
 */

import type { LayoutItem } from "@/components/dashboard/erp/widget-grid";

export interface DashboardLayoutResponse {
  layout: LayoutItem[];
  updated_at: string | null;
}

export interface EventPayload {
  widget_id: string;
  event: "open" | "hide";
}

/**
 * Fetch the effective layout for the current user.
 * Returns user override if it exists, otherwise tenant default.
 */
export async function fetchLayout(): Promise<DashboardLayoutResponse> {
  const response = await fetch("/api/v1/dashboards/me", {
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    console.warn(`Layout API returned ${response.status}: ${response.statusText}`);
    throw new Error(`Failed to fetch layout: ${response.status}`);
  }
  return response.json();
}

/**
 * Save the user's personal dashboard layout.
 */
export async function saveLayout(layout: LayoutItem[]): Promise<DashboardLayoutResponse> {
  const response = await fetch("/api/v1/dashboards/me", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ layout }),
  });
  if (!response.ok) {
    throw new Error(`Failed to save layout: ${response.status}`);
  }
  return response.json();
}

/**
 * Reset the user's layout to the tenant default.
 */
export async function resetLayout(): Promise<void> {
  const response = await fetch("/api/v1/dashboards/me/reset", {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Failed to reset layout: ${response.status}`);
  }
}

/**
 * Record widget interaction events (batched).
 */
export async function recordEvents(events: EventPayload[]): Promise<void> {
  if (events.length === 0) return;
  const response = await fetch("/api/v1/dashboards/me/events", {
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
 * Request an AI-powered layout suggestion from the ai-agent service.
 */
export async function fetchAiSuggestion(): Promise<{
  suggested_layout: LayoutItem[];
  reasoning: string;
  confidence: number;
}> {
  const response = await fetch("/api/v1/ai/dashboards/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch AI suggestion: ${response.status}`);
  }
  return response.json();
}
