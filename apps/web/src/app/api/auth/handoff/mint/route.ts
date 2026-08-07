import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  assertSameOrigin,
  backendError,
  callBackend,
  hostSurface,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

function workspaceUrl(request: NextRequest, slug: string): string {
  const { protocol, hostname, port } = request.nextUrl;
  const apex = hostname.split(".").slice(1).join(".") || hostname;
  return `${protocol}//${slug}.${apex}${port ? `:${port}` : ""}`;
}

/**
 * Mint a single-use, tenant-bound handoff token (POST body only, never in the
 * URL). Only auth origins (signup/signin) may mint; the workspace host never
 * does. The refresh token rides inside the payload so the workspace origin can
 * establish its host-scoped session cookie on redemption.
 */
export async function POST(request: NextRequest) {
  const { surface, slug } = hostSurface(request.headers.get("host"));
  if (surface !== "signup" && surface !== "signin") {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const refreshToken = request.cookies.get(SESSION_COOKIE)?.value;
  if (!refreshToken) {
    return NextResponse.json({ error: "Session expired." }, { status: 401 });
  }

  const body = (await request.json().catch(() => ({}))) as { redirect?: unknown };
  const redirect =
    typeof body.redirect === "string" && body.redirect.startsWith("/")
      ? body.redirect
      : "/";

  const result = await callBackend("/handoffs", {
    body: {
      purpose: "session",
      payload: { refresh_token: refreshToken, tenant_slug: slug, redirect },
    },
    tenantSlug: slug,
  });
  if (!result.ok) return backendError(result);

  const data = result.data;
  if (!data?.token) {
    return NextResponse.json({ error: "Could not mint handoff token." }, { status: 502 });
  }

  return NextResponse.json({
    token: String(data.token),
    workspaceUrl: workspaceUrl(request, slug),
    redirect,
  });
}
