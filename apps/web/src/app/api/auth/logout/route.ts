import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  applySessionCookie,
  assertSameOrigin,
  callBackend,
  resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const accessToken = typeof body.accessToken === "string" ? body.accessToken : null;
  const refreshToken = request.cookies.get(SESSION_COOKIE)?.value;
  const slug = resolveTenantSlug(request.headers.get("host"));

  const response = NextResponse.json({ status: "logged_out" });

  if (refreshToken) {
    if (accessToken) {
      await callBackend("/auth/logout", {
        body: { refresh_token: refreshToken },
        token: accessToken,
        tenantSlug: slug,
      });
    }
    applySessionCookie(response, null);
  }

  return response;
}
