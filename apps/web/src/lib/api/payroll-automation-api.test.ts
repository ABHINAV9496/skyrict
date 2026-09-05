import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createPayrollSchedule,
  deletePayrollSchedule,
  enqueuePayrollBatch,
  getPayrollPreferences,
  listPayrollBatches,
  listPayrollNotifications,
  listPayrollSchedules,
  runPayrollAutomationTick,
  updatePayrollPreferences,
  updatePayrollSchedule,
} from "@/lib/api/payroll-automation-api";

const httpMock = vi.fn<
  (path: string, options?: RequestInit) => Promise<{ data?: unknown; meta?: unknown }>
>();

type Envelope = { data?: unknown; meta?: unknown };

/**
 * Simulate the real http helpers: `apiFetchEnvelope` returns the whole
 * envelope, while `apiFetch`/`apiPost`/... unwrap `payload.data`. This mirrors
 * lib/api/http.ts so a regression back to `apiFetch` for a list endpoint
 * (which hands mapList the bare array) is caught by the tests.
 */
vi.mock("@/lib/api/http", () => ({
  apiFetch: async (_path: string, _options?: RequestInit) => {
    const result = await httpMock(_path, _options ?? {});
    return (result as Envelope).data;
  },
  apiFetchEnvelope: (_path: string, _options?: RequestInit) =>
    httpMock(_path, _options),
  apiPost: async (_path: string) => {
    const result = await httpMock(_path, { method: "POST" });
    return (result as Envelope).data;
  },
  apiPatch: async (_path: string) => {
    const result = await httpMock(_path, { method: "PATCH" });
    return (result as Envelope).data;
  },
  apiDelete: async (_path: string) => {
    const result = await httpMock(_path, { method: "DELETE" });
    return (result as Envelope).data;
  },
  buildQueryString: (params: Record<string, unknown>) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      search.set(key, String(value));
    }
    const query = search.toString();
    return query ? `?${query}` : "";
  },
  apiList: async <T>(
    path: string,
    input: {
      page?: number;
      pageSize?: number;
      query?: Record<string, string | number | boolean | null | undefined>;
    } = {},
  ) => {
    const page = Math.max(1, input.page ?? 1);
    const pageSize = Math.max(1, Math.min(input.pageSize ?? 20, 100));
    const offset = (page - 1) * pageSize;
    const probeLimit = Math.min(pageSize + 1, 100);
    const search = new URLSearchParams();
    search.set("limit", String(probeLimit));
    search.set("offset", String(offset));
    for (const [key, value] of Object.entries(input.query ?? {})) {
      if (value === undefined || value === null || value === "") continue;
      search.set(key, String(value));
    }
    const query = search.toString();
    const result = (await httpMock(`${path}${query ? `?${query}` : ""}`, {})) as {
      data?: T[];
    };
    const all = result.data ?? [];
    const hasMore = all.length > pageSize;
    return {
      items: hasMore ? all.slice(0, pageSize) : all,
      meta: {
        total: offset + all.length,
        page,
        page_size: pageSize,
        total_pages: hasMore ? page + 1 : page,
      },
    };
  },
}));

describe("payroll automation schedules", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("maps the schedules list into camelCase", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          schedule_id: "s-1",
          tenant_id: "t-1",
          name: "Monthly close",
          cron_expression: "0 18 1 * *",
          enabled: true,
          last_fired_at: "2026-08-01T18:00:00Z",
          next_run_at: "2026-09-01T18:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listPayrollSchedules();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/schedules", {});
    expect(result).toEqual([
      {
        scheduleId: "s-1",
        tenantId: "t-1",
        name: "Monthly close",
        cronExpression: "0 18 1 * *",
        enabled: true,
        lastFiredAt: "2026-08-01T18:00:00Z",
        nextRunAt: "2026-09-01T18:00:00Z",
      },
    ]);
  });

  it("posts a new schedule with snake_case body and maps the result", async () => {
    httpMock.mockResolvedValue({
      data: {
        schedule_id: "s-2",
        tenant_id: "t-1",
        name: "Payday eve",
        cron_expression: "0 9 28 * *",
        enabled: true,
        last_fired_at: null,
        next_run_at: "2026-09-28T09:00:00Z",
      },
    });

    const result = await createPayrollSchedule({
      name: "Payday eve",
      cronExpression: "0 9 28 * *",
    });

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/schedules", {
      method: "POST",
    });
    expect(result).toMatchObject({ name: "Payday eve", cronExpression: "0 9 28 * *" });
  });

  it("patches a schedule with the snake_case body", async () => {
    httpMock.mockResolvedValue({
      data: {
        schedule_id: "s-2",
        tenant_id: "t-1",
        name: "Payday eve",
        cron_expression: "0 9 28 * *",
        enabled: false,
        last_fired_at: null,
        next_run_at: null,
      },
    });

    const result = await updatePayrollSchedule("s-2", {
      name: "Payday eve",
      cronExpression: "0 9 28 * *",
      enabled: false,
    });

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/schedules/s-2", {
      method: "PATCH",
    });
    expect(result.enabled).toBe(false);
  });

  it("deletes a schedule by id", async () => {
    httpMock.mockResolvedValue({ data: {} });

    await deletePayrollSchedule("s-2");

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/schedules/s-2", {
      method: "DELETE",
    });
  });
});

describe("payroll automation notifications", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("lists notifications with the event_type filter omitted when empty", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          notification_id: "n-1",
          recipient_user_id: "u-1",
          event_type: "payslip_ready",
          in_app: true,
          email_stub: false,
          subject: "Payslip ready",
          body: "Your payslip for August is ready.",
          batch_id: null,
          run_id: "r-1",
          employee_id: "e-1",
          created_at: "2026-08-31T10:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listPayrollNotifications();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/notifications", {});
    expect(result[0]).toMatchObject({
      notificationId: "n-1",
      eventType: "payslip_ready",
      inApp: true,
      emailStub: false,
      runId: "r-1",
    });
  });

  it("narrows the notifications query when an event type is given", async () => {
    httpMock.mockResolvedValue({ data: [], meta: { total: 0, page: 1, page_size: 20, total_pages: 0 } });

    await listPayrollNotifications({ eventType: "payroll_batch_digest", limit: 25 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/ai/payroll/notifications?event_type=payroll_batch_digest&limit=25",
      {},
    );
  });
});

describe("payroll automation preferences", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("reads preferences and maps to booleans", async () => {
    httpMock.mockResolvedValue({
      data: { user_id: "u-1", in_app_on: true, email_on: false },
    });

    const result = await getPayrollPreferences();

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/ai/payroll/notifications/preferences",
      {},
    );
    expect(result).toEqual({ userId: "u-1", inAppOn: true, emailOn: false });
  });

  it("updates preferences with the snake_case body", async () => {
    httpMock.mockResolvedValue({
      data: { user_id: "u-1", in_app_on: true, email_on: true },
    });

    const result = await updatePayrollPreferences({ inAppOn: true, emailOn: true });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/ai/payroll/notifications/preferences",
      { method: "PUT", body: JSON.stringify({ in_app_on: true, email_on: true }) },
    );
    expect(result.emailOn).toBe(true);
  });
});

describe("payroll automation batches and tick", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("maps the batches list with pagination", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          batch_id: "b-1",
          tenant_id: "t-1",
          source: "manual",
          source_ref: "PR-2026-09",
          status: "completed",
          dry_run: false,
          totals: { employees: 5 },
          created_at: "2026-09-01T10:00:00Z",
          started_at: "2026-09-01T10:00:00Z",
          finished_at: "2026-09-01T10:00:05Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listPayrollBatches({ page: 1, pageSize: 20 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/ai/payroll/batches?limit=21&offset=0",
      {},
    );
    expect(result.items[0]).toMatchObject({
      batchId: "b-1",
      status: "completed",
      sourceRef: "PR-2026-09",
    });
  });

  it("enqueues a batch and maps the dry-run preflight result", async () => {
    httpMock.mockResolvedValue({
      data: {
        batch_id: "b-2",
        tenant_id: "t-1",
        source: "manual",
        source_ref: "PR-2026-09",
        status: "queued",
        dry_run: true,
        claimed_by: null,
        preflight: {
          version: 1,
          passed: true,
          checked_at: "2026-09-01T10:00:00Z",
          run_id: "run-1",
          roster_count: 5,
          checks: { settings: { status: "ok", detail: "settings row present" } },
          blocks: [],
          warnings: [],
        },
        totals: {},
        created_at: "2026-09-01T10:00:00Z",
        started_at: null,
        finished_at: null,
      },
    });

    const result = await enqueuePayrollBatch({ runId: "run-1", dryRun: true });

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/batches", {
      method: "POST",
    });
    expect(result).toMatchObject({
      batchId: "b-2",
      status: "queued",
      dryRun: true,
      sourceRef: "PR-2026-09",
    });
    expect((result.preflight as Record<string, unknown>).passed).toBe(true);
  });

  it("maps the manual tick result", async () => {    httpMock.mockResolvedValue({
      data: {
        batch_id: "b-9",
        items_processed: 4,
        status_changed: true,
        schedules_fired: 1,
      },
    });

    const result = await runPayrollAutomationTick();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/payroll/tick", {
      method: "POST",
    });
    expect(result).toEqual({
      batchId: "b-9",
      itemsProcessed: 4,
      statusChanged: true,
      schedulesFired: 1,
    });
  });
});