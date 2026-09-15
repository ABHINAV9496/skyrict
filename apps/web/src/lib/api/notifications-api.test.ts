import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  getNotificationCounts,
  listNotificationInbox,
  listNotificationPreferences,
  markAllNotificationsRead,
  markNotificationRead,
  snoozeNotification,
  updateNotificationPreference,
} from "@/lib/api/notifications-api";
import type { apiFetchEnvelope } from "@/lib/api/http";

const httpMock = vi.fn<typeof apiFetchEnvelope>();

type Envelope = { data?: unknown; meta?: unknown };

/**
 * Simulate the real http helpers: `apiFetch` unwraps `payload.data`, matching
 * lib/api/http.ts so a regression that changes the unwrap contract is caught.
 */
vi.mock("@/lib/api/http", () => ({
  apiFetch: async (_path: string, _options: RequestInit = {}) => {
    const result = await httpMock(_path, _options);
    return (result as Envelope).data;
  },
  apiFetchEnvelope: (_path: string, _options?: RequestInit) =>
    httpMock(_path, _options),
  apiPost: async (_path: string, _body?: unknown) => {
    const result = await httpMock(_path, {
      method: "POST",
      body: JSON.stringify(_body),
    });
    return (result as Envelope).data;
  },
}));

const item = {
  id: "594b6a6c-3c18-4114-9c2d-8c37a4b5c811",
  event_type: "inventory.low_stock",
  category: "inventory_alerts",
  module: "inventory",
  severity: "high",
  title: "Low stock: SKU-1001",
  body: "Steel bracket is below reorder point.",
  priority_score: 64,
  is_pinned: true,
  is_dismissible: true,
  is_digest: false,
  digest_count: null,
  occurred_at: "2026-09-13T09:00:00Z",
  read_at: null,
  snoozed_until: null,
  payload: { sku: "SKU-1001" },
};

describe("notification inbox and counts", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("lists the inbox and passes limit/offset/unread_only", async () => {
    httpMock.mockResolvedValue({
      data: {
        items: [item],
        total: 1,
        unread_count: 1,
        pinned_unread_count: 1,
      },
      meta: null,
    });

    const page = await listNotificationInbox(50, 0, undefined, true);

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/notifications/inbox?limit=50&offset=0&unread_only=true",
      {},
    );
    expect(page).toEqual({
      items: [item],
      total: 1,
      unread_count: 1,
      pinned_unread_count: 1,
    });
  });

  it("appends the category filter when given", async () => {
    httpMock.mockResolvedValue({
      data: { items: [], total: 0, unread_count: 0, pinned_unread_count: 0 },
      meta: null,
    });

    await listNotificationInbox(25, 10, "compliance");

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/notifications/inbox?limit=25&offset=10&unread_only=false&category=compliance",
      {},
    );
  });

  it("reads the unread/pinned counts for the bell badge", async () => {
    httpMock.mockResolvedValue({
      data: { unread_count: 3, pinned_unread_count: 1 },
      meta: null,
    });

    const counts = await getNotificationCounts();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/notifications/counts", {});
    expect(counts).toEqual({ unread_count: 3, pinned_unread_count: 1 });
  });
});

describe("notification mutations", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("marks one notification read", async () => {
    httpMock.mockResolvedValue({
      data: { id: item.id, read_at: "2026-09-13T10:00:00Z" },
      meta: null,
    });

    const result = await markNotificationRead(item.id);

    expect(httpMock).toHaveBeenCalledWith(
      `/api/v1/notifications/${item.id}/read`,
      { method: "POST", body: "{}" },
    );
    expect(result.read_at).toBe("2026-09-13T10:00:00Z");
  });

  it("marks the whole inbox read", async () => {
    httpMock.mockResolvedValue({ data: { marked: 2 }, meta: null });

    const result = await markAllNotificationsRead();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/notifications/read-all", {
      method: "POST",
      body: "{}",
    });
    expect(result.marked).toBe(2);
  });

  it("snoozes until the given ISO timestamp", async () => {
    httpMock.mockResolvedValue({ data: { snoozed: true, mandated: false }, meta: null });

    const result = await snoozeNotification(item.id, "2026-09-14T09:00:00Z");

    expect(httpMock).toHaveBeenCalledWith(
      `/api/v1/notifications/${item.id}/snooze`,
      {
        method: "POST",
        body: JSON.stringify({ until: "2026-09-14T09:00:00Z" }),
      },
    );
    expect(result.snoozed).toBe(true);
  });
});

describe("notification preferences", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("lists preferences and unwraps the items array", async () => {
    httpMock.mockResolvedValue({
      data: {
        items: [
          {
            category: "compliance",
            label: "Compliance",
            mandatory: true,
            in_app_on: true,
            email_on: true,
            webhook_on: false,
          },
          {
            category: "inventory_alerts",
            label: "Inventory alerts",
            mandatory: false,
            in_app_on: true,
            email_on: false,
            webhook_on: false,
          },
        ],
      },
      meta: null,
    });

    const prefs = await listNotificationPreferences();

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/notifications/preferences",
      {},
    );
    expect(prefs).toHaveLength(2);
    expect(prefs[0]).toMatchObject({
      category: "compliance",
      mandatory: true,
      in_app_on: true,
    });
  });

  it("updates one category via PUT", async () => {
    httpMock.mockResolvedValue({
      data: {
        category: "inventory_alerts",
        label: "Inventory alerts",
        mandatory: false,
        in_app_on: true,
        email_on: true,
        webhook_on: false,
      },
      meta: null,
    });

    const result = await updateNotificationPreference("inventory_alerts", {
      in_app_on: true,
      email_on: true,
      webhook_on: false,
    });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/notifications/preferences/inventory_alerts",
      {
        method: "PUT",
        body: JSON.stringify({
          in_app_on: true,
          email_on: true,
          webhook_on: false,
        }),
      },
    );
    expect(result.email_on).toBe(true);
  });
});