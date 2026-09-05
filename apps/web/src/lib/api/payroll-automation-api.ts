/**
 * Payroll automation API client (batches, schedules, notifications, digests).
 *
 * Mirrors payroll-api.ts: calls go through the same-origin /api/v1/* BFF
 * proxy (the "ai" segment routes to core), payloads are mapped from
 * snake_case over the wire to camelCase here, and every failure surfaces an
 * `ApiError` the UI can render inline.
 */

import {
  ApiError,
  apiDelete,
  apiFetch,
  apiList,
  apiPatch,
  apiPost,
  buildQueryString,
  type Paginated,
} from "@/lib/api/http";

export type PayrollBatchStatus = "queued" | "processing" | "completed" | "failed" | "aborted";

export interface PayrollBatch {
  batchId: string;
  tenantId: string;
  source: string;
  sourceRef: string;
  status: PayrollBatchStatus;
  dryRun: boolean;
  claimedBy: string | null;
  preflight: Record<string, unknown> | null;
  totals: Record<string, unknown>;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface PayrollBatchListItem {
  batchId: string;
  tenantId: string;
  source: string;
  sourceRef: string;
  status: PayrollBatchStatus;
  dryRun: boolean;
  totals: Record<string, unknown>;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface PayrollBatchTick {
  batchId: string | null;
  itemsProcessed: number;
  statusChanged: boolean;
  schedulesFired: number;
}

export interface PayrollSchedule {
  scheduleId: string;
  tenantId: string;
  name: string | null;
  cronExpression: string;
  enabled: boolean;
  lastFiredAt: string | null;
  nextRunAt: string | null;
}

export type PayrollNotificationEventType = "payslip_ready" | "payroll_batch_digest";

export interface PayrollNotification {
  notificationId: string;
  recipientUserId: string;
  eventType: PayrollNotificationEventType;
  inApp: boolean;
  emailStub: boolean;
  subject: string;
  body: string;
  batchId: string | null;
  runId: string | null;
  employeeId: string | null;
  createdAt: string | null;
}

export interface PayrollPreferences {
  userId: string;
  inAppOn: boolean;
  emailOn: boolean;
}

interface PayrollBatchPayload {
  batch_id?: unknown;
  tenant_id?: unknown;
  source?: unknown;
  source_ref?: unknown;
  status?: unknown;
  dry_run?: unknown;
  claimed_by?: unknown;
  preflight?: unknown;
  totals?: unknown;
  created_at?: unknown;
  started_at?: unknown;
  finished_at?: unknown;
}

interface PayrollBatchTickPayload {
  batch_id?: unknown;
  items_processed?: unknown;
  status_changed?: unknown;
  schedules_fired?: unknown;
}

interface PayrollSchedulePayload {
  schedule_id?: unknown;
  tenant_id?: unknown;
  name?: unknown;
  cron_expression?: unknown;
  enabled?: unknown;
  last_fired_at?: unknown;
  next_run_at?: unknown;
}

interface PayrollNotificationPayload {
  notification_id?: unknown;
  recipient_user_id?: unknown;
  event_type?: unknown;
  in_app?: unknown;
  email_stub?: unknown;
  subject?: unknown;
  body?: unknown;
  batch_id?: unknown;
  run_id?: unknown;
  employee_id?: unknown;
  created_at?: unknown;
}

interface PayrollPreferencesPayload {
  user_id?: unknown;
  in_app_on?: unknown;
  email_on?: unknown;
}

function mapBatchStatus(value: unknown): PayrollBatchStatus {
  switch (value) {
    case "queued":
    case "processing":
    case "completed":
    case "failed":
    case "aborted":
      return value;
    default:
      return "queued";
  }
}

function mapBatch(payload: PayrollBatchPayload): PayrollBatch {
  return {
    batchId: String(payload.batch_id ?? ""),
    tenantId: String(payload.tenant_id ?? ""),
    source: String(payload.source ?? ""),
    sourceRef: String(payload.source_ref ?? ""),
    status: mapBatchStatus(payload.status),
    dryRun: payload.dry_run === true,
    claimedBy: typeof payload.claimed_by === "string" ? payload.claimed_by : null,
    preflight:
      payload.preflight !== null && typeof payload.preflight === "object"
        ? (payload.preflight as Record<string, unknown>)
        : null,
    totals:
      payload.totals !== null && typeof payload.totals === "object"
        ? (payload.totals as Record<string, unknown>)
        : {},
    startedAt: typeof payload.started_at === "string" ? payload.started_at : null,
    finishedAt: typeof payload.finished_at === "string" ? payload.finished_at : null,
  };
}

function mapBatchListItem(payload: PayrollBatchPayload): PayrollBatchListItem {
  return {
    batchId: String(payload.batch_id ?? ""),
    tenantId: String(payload.tenant_id ?? ""),
    source: String(payload.source ?? ""),
    sourceRef: String(payload.source_ref ?? ""),
    status: mapBatchStatus(payload.status),
    dryRun: payload.dry_run === true,
    totals:
      payload.totals !== null && typeof payload.totals === "object"
        ? (payload.totals as Record<string, unknown>)
        : {},
    createdAt: typeof payload.created_at === "string" ? payload.created_at : null,
    startedAt: typeof payload.started_at === "string" ? payload.started_at : null,
    finishedAt: typeof payload.finished_at === "string" ? payload.finished_at : null,
  };
}

function mapTick(payload: PayrollBatchTickPayload | null): PayrollBatchTick {
  const next = payload ?? {};
  return {
    batchId: typeof next.batch_id === "string" ? next.batch_id : null,
    itemsProcessed: typeof next.items_processed === "number" ? next.items_processed : 0,
    statusChanged: next.status_changed === true,
    schedulesFired: typeof next.schedules_fired === "number" ? next.schedules_fired : 0,
  };
}

function mapSchedule(payload: PayrollSchedulePayload | null): PayrollSchedule {
  const next = payload ?? {};
  return {
    scheduleId: String(next.schedule_id ?? ""),
    tenantId: String(next.tenant_id ?? ""),
    name: typeof next.name === "string" && next.name ? next.name : null,
    cronExpression: String(next.cron_expression ?? ""),
    enabled: next.enabled !== false,
    lastFiredAt: typeof next.last_fired_at === "string" ? next.last_fired_at : null,
    nextRunAt: typeof next.next_run_at === "string" ? next.next_run_at : null,
  };
}

function mapNotification(payload: PayrollNotificationPayload): PayrollNotification {
  return {
    notificationId: String(payload.notification_id ?? ""),
    recipientUserId: String(payload.recipient_user_id ?? ""),
    eventType: String(payload.event_type ?? "payroll_batch_digest") as PayrollNotificationEventType,
    inApp: payload.in_app === true,
    emailStub: payload.email_stub === true,
    subject: String(payload.subject ?? ""),
    body: String(payload.body ?? ""),
    batchId: typeof payload.batch_id === "string" ? payload.batch_id : null,
    runId: typeof payload.run_id === "string" ? payload.run_id : null,
    employeeId: typeof payload.employee_id === "string" ? payload.employee_id : null,
    createdAt: typeof payload.created_at === "string" ? payload.created_at : null,
  };
}

function mapPreferences(payload: PayrollPreferencesPayload | null): PayrollPreferences | null {
  if (!payload) return null;
  return {
    userId: String(payload.user_id ?? ""),
    inAppOn: payload.in_app_on !== false,
    emailOn: payload.email_on === true,
  };
}

export async function enqueuePayrollBatch(input: {
  runId: string;
  dryRun?: boolean;
}): Promise<PayrollBatch> {
  const raw = await apiPost<PayrollBatchPayload>("/api/v1/ai/payroll/batches", {
    run_id: input.runId,
    dry_run: input.dryRun ?? false,
  });
  return mapBatch(raw ?? {});
}

export async function listPayrollBatches(input: {
  page?: number;
  pageSize?: number;
  status?: PayrollBatchStatus;
} = {}): Promise<Paginated<PayrollBatchListItem>> {
  const result = await apiList<PayrollBatchPayload>("/api/v1/ai/payroll/batches", {
    page: input.page,
    pageSize: input.pageSize,
    query: { status: input.status },
  });
  return { items: result.items.map(mapBatchListItem), meta: result.meta };
}

export async function getPayrollBatch(batchId: string): Promise<PayrollBatch> {
  const raw = await apiFetch<PayrollBatchPayload>(`/api/v1/ai/payroll/batches/${batchId}`);
  return mapBatch(raw ?? {});
}

export async function runPayrollAutomationTick(): Promise<PayrollBatchTick> {
  const raw = await apiPost<PayrollBatchTickPayload>("/api/v1/ai/payroll/tick", {});
  return mapTick(raw ?? null);
}

export async function listPayrollSchedules(): Promise<PayrollSchedule[]> {
  const items = await apiFetch<PayrollSchedulePayload[]>("/api/v1/ai/payroll/schedules");
  return (items ?? []).map(mapSchedule);
}

export async function createPayrollSchedule(input: {
  name?: string;
  cronExpression: string;
  enabled?: boolean;
}): Promise<PayrollSchedule> {
  const raw = await apiPost<PayrollSchedulePayload>("/api/v1/ai/payroll/schedules", {
    name: input.name,
    cron_expression: input.cronExpression,
    enabled: input.enabled ?? true,
  });
  return mapSchedule(raw ?? null);
}

export async function updatePayrollSchedule(
  scheduleId: string,
  input: {
    name?: string;
    cronExpression: string;
    enabled?: boolean;
  },
): Promise<PayrollSchedule> {
  const raw = await apiPatch<PayrollSchedulePayload>(
    `/api/v1/ai/payroll/schedules/${scheduleId}`,
    {
      name: input.name,
      cron_expression: input.cronExpression,
      enabled: input.enabled ?? true,
    },
  );
  return mapSchedule(raw ?? null);
}

export async function deletePayrollSchedule(scheduleId: string): Promise<void> {
  await apiDelete<{ data?: unknown }>(`/api/v1/ai/payroll/schedules/${scheduleId}`);
}

export async function listPayrollNotifications(input: {
  eventType?: PayrollNotificationEventType;
  limit?: number;
} = {}): Promise<PayrollNotification[]> {
  const items = await apiFetch<PayrollNotificationPayload[]>(
    `/api/v1/ai/payroll/notifications${buildQueryString({
      event_type: input.eventType,
      limit: input.limit,
    })}`,
  );
  return (items ?? []).map(mapNotification);
}

export async function getPayrollPreferences(): Promise<PayrollPreferences | null> {
  const raw = await apiFetch<PayrollPreferencesPayload | null>(
    "/api/v1/ai/payroll/notifications/preferences",
  );
  return mapPreferences(raw ?? null);
}

export async function updatePayrollPreferences(input: {
  inAppOn: boolean;
  emailOn: boolean;
}): Promise<PayrollPreferences> {
  const raw = await apiFetch<PayrollPreferencesPayload>(
    "/api/v1/ai/payroll/notifications/preferences",
    {
      method: "PUT",
      body: JSON.stringify({
        in_app_on: input.inAppOn,
        email_on: input.emailOn,
      }),
    },
  );
  const preferences = mapPreferences(raw ?? null);
  if (!preferences) throw new ApiError(502, "Preferences update returned an empty response.");
  return preferences;
}