import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  applySessionCookie,
  callBackend,
  mapUser,
  resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * Restore a session: refresh the access token from the httpOnly cookie, then
 * fetch the profile. The browser keeps the access token in memory; this route
 * re-hydrates it on page load and lets server components guard routes.
 */
export async function GET(request: NextRequest) {
  const refreshToken = request.cookies.get(SESSION_COOKIE)?.value;
  if (!refreshToken) {
    return NextResponse.json({ authenticated: false });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const refreshed = await callBackend("/auth/refresh", {
    body: { refresh_token: refreshToken },
    tenantSlug: slug,
  });
  if (!refreshed.ok) {
    const response = NextResponse.json({ authenticated: false });
    if (refreshed.status === 401 || refreshed.status === 0) applySessionCookie(response, null);
    return response;
  }

  const data = refreshed.data;
  if (!data?.access_token) {
    return NextResponse.json({ authenticated: false });
  }

  const profile = await callBackend("/users/me", {
    method: "GET",
    token: String(data.access_token),
    tenantSlug: slug,
  });

  const response = NextResponse.json({
    authenticated: profile.ok,
    accessToken: profile.ok ? String(data.access_token) : null,
    expiresIn: data.expires_in ?? 0,
    user: profile.ok ? mapUser(profile.data) : null,
  });
  if (profile.ok && data.refresh_token) applySessionCookie(response, String(data.refresh_token));
  return response;
}
