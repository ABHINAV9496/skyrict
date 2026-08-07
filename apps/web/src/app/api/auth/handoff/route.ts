import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  applySessionCookie,
  backendError,
  callBackend,
  hostSurface,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

const ALLOWED_ORIGIN =
  /^https?:\/\/(?:signup\.|(?:[a-z0-9-]+)\.signin\.)(?:localhost|skyrict\.com)(?::\d+)?$/;

function allowedOrigin(origin: string | null): boolean {
  if (!origin) return true;
  return ALLOWED_ORIGIN.test(origin.toLowerCase());
}

function allowedRedirect(path: string): boolean {
  if (path.includes("//") || path.includes("..") || path.includes(":") || path.includes("\\")) {
    return false;
  }
  return path === "/" || /^\/[a-zA-Z0-9][a-zA-Z0-9/_-]*$/.test(path);
}

function applyCors(response: NextResponse, origin: string | null): void {
  if (!origin) return;
  response.headers.set("Access-Control-Allow-Origin", origin);
  response.headers.set("Vary", "Origin");
  response.headers.set("Access-Control-Allow-Methods", "POST, OPTIONS");
  response.headers.set("Access-Control-Allow-Headers", "Content-Type");
}

/** Cross-origin preflight: the workspace origin accepts auth-origin POSTs. */
export async function OPTIONS(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (!allowedOrigin(origin)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }
  const response = new NextResponse(null, { status: 204 });
  applyCors(response, origin);
  return response;
}

/**
 * Redeem a handoff token on the workspace origin: consumes the single-use
 * token, host-locks it to the Host tenant, exchanges the embedded refresh
 * token for a fresh pair, and sets the host-scoped httpOnly session cookie.
 */
export async function POST(request: NextRequest) {
  const { surface, slug } = hostSurface(request.headers.get("host"));
  if (surface !== "workspace" || !slug) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const origin = request.headers.get("origin");
  if (!allowedOrigin(origin)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const body = (await request.json().catch(() => ({}))) as { token?: unknown };
  const token = typeof body.token === "string" ? body.token : "";
  if (!token) {
    return NextResponse.json({ error: "Handoff token is required." }, { status: 400 });
  }

  const redeem = await callBackend("/handoffs/redeem", {
    body: { token, purpose: "session" },
    tenantSlug: slug,
  });
  if (!redeem.ok) return backendError(redeem);

  const payload = (redeem.data?.payload ?? {}) as Record<string, unknown>;
  if (payload.tenant_slug !== slug) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const refreshToken = payload.refresh_token;
  const redirect = payload.redirect;
  if (
    typeof refreshToken !== "string" ||
    typeof redirect !== "string" ||
    !allowedRedirect(redirect)
  ) {
    return NextResponse.json({ error: "Invalid handoff payload." }, { status: 400 });
  }

  const refreshed = await callBackend("/auth/refresh", {
    body: { refresh_token: refreshToken },
    tenantSlug: slug,
  });
  if (!refreshed.ok) {
    const clear = backendError(refreshed);
    applySessionCookie(clear, null);
    applyCors(clear, origin);
    return clear;
  }

  const data = refreshed.data;
  if (!data?.access_token) {
    const response = NextResponse.json(
      { error: "Unexpected handoff response." },
      { status: 502 },
    );
    applyCors(response, origin);
    return response;
  }

  const response = NextResponse.json({ ok: true, redirect });
  if (data.refresh_token) applySessionCookie(response, String(data.refresh_token));
  applyCors(response, origin);
  return response;
}
