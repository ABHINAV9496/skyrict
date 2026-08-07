import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  applySessionCookie,
  assertSameOrigin,
  backendError,
  callBackend,
  mapUser,
  resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!email || !password) {
    return NextResponse.json({ error: "Email and password are required." }, { status: 400 });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const result = await callBackend("/auth/login", { body: { email, password }, tenantSlug: slug });
  if (!result.ok) return backendError(result);

  const data = result.data;
  if (!data) {
    return NextResponse.json({ error: "Unexpected login response." }, { status: 502 });
  }

  if (data.next_step === "mfa.verify") {
    return NextResponse.json({
      status: "mfa_challenge",
      mfaToken: data.mfa_token ?? null,
      user: mapUser(data.user as Record<string, unknown>),
    });
  }

  if (data.next_step === "mfa.setup") {
    const response = NextResponse.json({
      status: "mfa_setup",
      accessToken: data.access_token ?? null,
      expiresIn: data.expires_in ?? 0,
      user: mapUser(data.user as Record<string, unknown>),
    });
    if (data.refresh_token) applySessionCookie(response, String(data.refresh_token));
    return response;
  }

  if (data.access_token) {
    const response = NextResponse.json({
      status: "authenticated",
      accessToken: data.access_token,
      expiresIn: data.expires_in ?? 0,
      user: mapUser(data.user as Record<string, unknown>),
    });
    if (data.refresh_token) applySessionCookie(response, String(data.refresh_token));
    return response;
  }

  return NextResponse.json({ error: "Unexpected login response." }, { status: 502 });
}
