/**
 * Authenticated fetch wrapper for /api/v1 calls.
 *
 * Attaches the in-memory Bearer token and X-Tenant-Slug, and on a 401
 * performs a single-flight silent refresh through the BFF (the refresh token
 * lives in an httpOnly cookie the browser cannot read), then retries once.
 */

import { getAccessToken, getTenantSlug, setAccessToken } from "@/lib/auth/session-store";
import { browserSigninUrl } from "@/lib/auth/client-urls";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface PaginationMeta {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

let refreshPromise: Promise<boolean> | null = null;

let sessionLostRedirectPending = false;

/**
 * The session has definitively ended — the refresh token was rejected or
 * revoked. Clear the in-memory access token and leave the workspace origin
 * for the tenant's signin surface exactly once, so the app never keeps
 * retrying a dead session (which re-arms the backend's reuse detector and
 * re-logs the same revocation on every attempt).
 */
export function handleSessionLost(): void {
  if (typeof window === "undefined" || sessionLostRedirectPending) return;
  const target = browserSigninUrl();
  if (target === window.location.href) return;
  sessionLostRedirectPending = true;
  setAccessToken(null);
  window.location.assign(target);
}

function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", { method: "POST", cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          if (response.status === 401) handleSessionLost();
          return false;
        }
        const payload = (await response.json().catch(() => ({}))) as {
          status?: string;
          accessToken?: string | null;
        };
        if (payload.status === "authenticated" && payload.accessToken) {
          setAccessToken(payload.accessToken);
          return true;
        }
        return false;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

interface HydratedSession {
  accessToken: string;
  user: Record<string, unknown> | null;
}

let sessionPromise: Promise<HydratedSession | null> | null = null;

/**
 * Restore the in-memory access token from the httpOnly session cookie via
 * /api/auth/session, single-flight. Every consumer (SessionProvider and the
 * authenticated /api/v1 client) shares one request so that exactly one
 * server-side refresh-token rotation happens per page load — concurrent
 * rotations from the same token would be flagged as reuse and revoke the
 * whole token family.
 */
export function ensureSession(): Promise<HydratedSession | null> {
  if (getAccessToken()) {
    return Promise.resolve({ accessToken: getAccessToken() as string, user: null });
  }
  if (!sessionPromise) {
    sessionPromise = fetch("/api/auth/session", { cache: "no-store" })
      .then(async (response) => {
        if (response.status === 401) handleSessionLost();
        const payload = (await response.json().catch(() => ({}))) as {
          authenticated?: boolean;
          accessToken?: string | null;
          user?: Record<string, unknown> | null;
        };
        if (response.ok && payload.authenticated && payload.accessToken) {
          setAccessToken(payload.accessToken);
          return { accessToken: payload.accessToken, user: payload.user ?? null };
        }
        return null;
      })
      .finally(() => {
        sessionPromise = null;
      });
  }
  return sessionPromise;
}

async function toResult<T>(response: Response): Promise<T> {
  return readPayload<T>(response).then(({ data }) => data);
}

interface Envelope<T> {
  data: T;
  meta: PaginationMeta | null;
}

async function readPayload<T>(response: Response): Promise<Envelope<T>> {
  const payload = (await response.json().catch(() => ({}))) as {
    data?: T | null;
    meta?: PaginationMeta | null;
    detail?: { error?: { message?: string }; message?: string } | string;
  };
  if (!response.ok) {
    const message =
      (typeof payload.detail === "object" && payload.detail?.error?.message) ||
      (typeof payload.detail === "object" && payload.detail?.message) ||
      (typeof payload.detail === "string" ? payload.detail : null) ||
      "Request failed. Please try again.";
    throw new ApiError(response.status, message);
  }
  return { data: payload.data as T, meta: payload.meta ?? null };
}

/** Fetch a `/api/v1` endpoint with session hydration/refresh, returning the full envelope. */
async function fetchWithSession(path: string, options: RequestInit): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set("X-Tenant-Slug", getTenantSlug());
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response = await fetch(path, { ...options, headers });

  // A 401 means the access token is missing (fresh page load on the workspace
  // origin, where the token only lives in memory) or stale. Hydrate/refresh
  // silently through the BFF — the refresh token lives in an httpOnly cookie —
  // then retry once. If the refresh itself fails the session is gone and the
  // caller surfaces the 401. Both recovery paths are single-flight so exactly
  // one server-side token rotation happens at a time.
  if (response.status === 401) {
    if (token) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        const fresh = getAccessToken();
        headers.set("Authorization", `Bearer ${fresh ?? ""}`);
        response = await fetch(path, { ...options, headers });
      } else {
        setAccessToken(null);
      }
    } else {
      const session = await ensureSession();
      if (session) {
        headers.set("Authorization", `Bearer ${session.accessToken}`);
        response = await fetch(path, { ...options, headers });
      } else {
        setAccessToken(null);
        handleSessionLost();
      }
    }
  }

  return response;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  return toResult<T>(await fetchWithSession(path, options));
}

export async function apiFetchWithMeta<T>(
  path: string,
  options: RequestInit = {},
): Promise<Envelope<T>> {
  return readPayload<T>(await fetchWithSession(path, options));
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function apiDelete<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: "DELETE" });
}
