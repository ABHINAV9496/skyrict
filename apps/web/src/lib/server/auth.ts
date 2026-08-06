/**
 * Server-side auth BFF helpers.
 *
 * The browser never talks to the identity service's /auth/* endpoints
 * directly for login: it calls these same-origin route handlers, which
 * (a) enforce the Origin/Referer CSRF check, (b) resolve the tenant slug
 * from the Host header the same way the backend does, and (c) write the
 * refresh token into an httpOnly cookie. The access token is returned in
 * the JSON body and kept in memory by the client — never in storage, never
 * readable by third-party scripts.
 */

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

export const SESSION_COOKIE = "skyrict_session";

const SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

function apiBase(): string {
  return process.env.API_PROXY_TARGET ?? "http://localhost:8000";
}

/** Dev/prod tenant slug from the Host header, mirroring the backend middleware. */
export function resolveTenantSlug(host: string | null | undefined): string {
  const value = (host ?? "").trim().toLowerCase().replace(/:\d+$/, "");
  const match = /^([a-z0-9-]+)\.localhost$/.exec(value);
  if (match) return match[1];
  return process.env.TENANT_SLUG ?? "acme";
}

/**
 * CSRF gate for state-changing routes: the request must come from our own
 * origin (matching Host). SameSite=Lax already stops cross-site POSTs from
 * carrying the cookie; this is defense in depth for older browsers.
 */
export function assertSameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

interface BackendCallOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  token?: string | null;
  tenantSlug?: string | null;
}

interface BackendCallResult {
  ok: boolean;
  status: number;
  data: Record<string, unknown> | null;
  payload: Record<string, unknown>;
}

/** Proxy a call to the identity service, forwarding tenant + bearer context. */
export async function callBackend(
  path: string,
  options: BackendCallOptions = {},
): Promise<BackendCallResult> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.tenantSlug) headers["X-Tenant-Slug"] = options.tenantSlug;
  if (options.token) headers["Authorization"] = `Bearer ${options.token}`;

  let response: Response;
  try {
    response = await fetch(`${apiBase()}/api/v1${path}`, {
      method: options.method ?? "POST",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
    });
  } catch {
    return { ok: false, status: 0, data: null, payload: {} };
  }

  const payload = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  return {
    ok: response.ok,
    status: response.status,
    data: (payload.data as Record<string, unknown> | null) ?? null,
    payload,
  };
}

/** Map the backend snake_case user object to the frontend AuthUser shape. */
export function mapUser(raw: Record<string, unknown> | null | undefined) {
  if (!raw) return null;
  return {
    id: String(raw.id ?? ""),
    email: String(raw.email ?? ""),
    fullName: String(raw.full_name ?? raw.fullName ?? ""),
    isActive: Boolean(raw.is_active ?? raw.isActive),
    isVerified: Boolean(raw.is_verified ?? raw.isVerified),
    mfaEnabled: Boolean(raw.mfa_enabled ?? raw.mfaEnabled),
    createdAt: String(raw.created_at ?? raw.createdAt ?? ""),
  };
}

/** JSON error response mirroring the backend problem+json contract. */
export function backendError(result: BackendCallResult) {
  const detail = result.payload.detail ?? "Request failed. Please try again.";
  return NextResponse.json({ error: String(detail) }, { status: result.status || 400 });
}

/** Set (or clear, when value is null) the httpOnly refresh-token cookie. */
export function applySessionCookie(response: NextResponse, value: string | null): void {
  response.cookies.set(SESSION_COOKIE, value ?? "", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: value ? SESSION_MAX_AGE_SECONDS : 0,
  });
}
