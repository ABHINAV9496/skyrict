import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  applySessionCookie,
  backendError,
  callBackend,
  resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/** Silent refresh: rotate the httpOnly cookie and return a fresh access token. */
export async function POST(request: NextRequest) {
  const refreshToken = request.cookies.get(SESSION_COOKIE)?.value;
  if (!refreshToken) {
    return NextResponse.json({ status: "unauthenticated" }, { status: 401 });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const result = await callBackend("/auth/refresh", {
    body: { refresh_token: refreshToken },
    tenantSlug: slug,
  });
  if (!result.ok) {
    if (result.status === 401 || result.status === 0) {
      const clear = NextResponse.json({ status: "unauthenticated" }, { status: 401 });
      applySessionCookie(clear, null);
      return clear;
    }
    return backendError(result);
  }

  const data = result.data;
  if (!data?.access_token) {
    return NextResponse.json({ status: "unauthenticated" }, { status: 401 });
  }

  const response = NextResponse.json({
    status: "authenticated",
    accessToken: data.access_token,
    expiresIn: data.expires_in ?? 0,
  });
  if (data.refresh_token) applySessionCookie(response, String(data.refresh_token));
  return response;
}
