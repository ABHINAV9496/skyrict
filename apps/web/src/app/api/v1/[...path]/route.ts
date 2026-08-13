import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  assertSameOrigin,
  callBackend,
  resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

/**
 * Authenticated BFF proxy for internal services' /api/v1/* endpoints.
 *
 * The browser talks to these same-origin handlers instead of the backend:
 * (a) the tenant slug is always derived server-side from the Host header (the
 * client's X-Tenant-Slug is ignored), (b) the client's Bearer access token is
 * forwarded when present — on the workspace origin it is absent on first load,
 * so the backend answers 401 and the client's single-flight silent refresh
 * (/api/auth/refresh, driven by the httpOnly session cookie) retries once,
 * and (c) state-changing methods must pass the Origin/Referer CSRF gate.
 */
async function proxy(request: NextRequest) {
  if (SAFE_METHODS.has(request.method.toUpperCase()) === false && !assertSameOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin." }, { status: 403 });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const authorization = request.headers.get("authorization");

  const path = `/${request.nextUrl.pathname.replace(/^\/api\/v1\//, "")}${request.nextUrl.search}`;
  const segment = path.split("/")[1];
  const target = ["crm", "sales", "inventory"].includes(segment) ? "core" : "identity";
  const body =
    SAFE_METHODS.has(request.method.toUpperCase()) || !request.body
      ? undefined
      : await request.json().catch(() => undefined);

  const result = await callBackend(path, {
    method: request.method as "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
    body,
    tenantSlug: slug,
    token: authorization?.toLowerCase().startsWith("bearer ")
      ? authorization.slice("Bearer ".length)
      : null,
    target,
  });

  if (result.status === 0) {
    return NextResponse.json(
      { detail: "Identity service is unavailable. Please try again." },
      { status: 502 },
    );
  }

  return NextResponse.json(result.payload, { status: result.status });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
