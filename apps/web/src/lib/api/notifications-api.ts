import { apiFetch, apiPost } from "@/lib/api/http";

const NOTIFICATIONS = "/api/v1/notifications";

/** One notification row in the inbox / drawer responses. */
export interface NotificationItem {
    id: string;
    event_type: string;
    category: string;
    module: string;
    severity: string;
    title: string;
    body: string;
    priority_score: number;
    is_pinned: boolean;
    is_dismissible: boolean;
    is_digest: boolean;
    digest_count: number | null;
    occurred_at: string;
    read_at: string | null;
    snoozed_until: string | null;
    payload: Record<string, unknown> | null;
}

/** Paginated inbox payload (envelope's `data`). */
export interface InboxPage {
    items: NotificationItem[];
    total: number;
    unread_count: number;
    pinned_unread_count: number;
}

/** Unread + pinned-unread counters for the bell/drawer badge. */
export interface NotificationCounts {
    unread_count: number;
    pinned_unread_count: number;
}

export interface MarkReadResult {
    id: string;
    read_at: string;
}

export interface MarkAllReadResult {
    marked: number;
}

export interface SnoozeResult {
    snoozed: boolean;
    mandated: boolean;
}

/** One category's effective preference row. */
export interface NotificationPreference {
    category: string;
    label: string;
    mandatory: boolean;
    in_app_on: boolean;
    email_on: boolean;
    webhook_on: boolean;
}

export interface NotificationPreferenceUpdate {
    in_app_on: boolean;
    email_on: boolean;
    webhook_on: boolean;
}

/** Page the inbox; the backend caps `limit` at 200. */
export function listNotificationInbox(
    limit = 50,
    offset = 0,
    category?: string,
    unreadOnly = false,
): Promise<InboxPage> {
    const search = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
        unread_only: String(unreadOnly),
    });
    if (category) search.set("category", category);
    return apiFetch<InboxPage>(`${NOTIFICATIONS}/inbox?${search.toString()}`);
}

/** Unread/pinned counts backing the bell badge. */
export function getNotificationCounts(): Promise<NotificationCounts> {
    return apiFetch<NotificationCounts>(`${NOTIFICATIONS}/counts`);
}

/** Mark one notification read (the backend only allows your own rows). */
export function markNotificationRead(notificationId: string): Promise<MarkReadResult> {
    return apiPost<MarkReadResult>(`${NOTIFICATIONS}/${notificationId}/read`, {});
}

/** Mark the whole inbox read. */
export function markAllNotificationsRead(): Promise<MarkAllReadResult> {
    return apiPost<MarkAllReadResult>(`${NOTIFICATIONS}/read-all`, {});
}

/** Snooze one notification until the given ISO timestamp. */
export function snoozeNotification(
    notificationId: string,
    until: string,
): Promise<SnoozeResult> {
    return apiPost<SnoozeResult>(`${NOTIFICATIONS}/${notificationId}/snooze`, { until });
}

/** All category preferences for the current user. */
export function listNotificationPreferences(): Promise<NotificationPreference[]> {
    return apiFetch<{ items: NotificationPreference[] }>(
        `${NOTIFICATIONS}/preferences`,
    ).then((body) => body.items);
}

/** Upsert one category's preferences. */
export function updateNotificationPreference(
    category: string,
    update: NotificationPreferenceUpdate,
): Promise<NotificationPreference> {
    return apiFetch<NotificationPreference>(
        `${NOTIFICATIONS}/preferences/${category}`,
        {
            method: "PUT",
            body: JSON.stringify(update),
        },
    );
}