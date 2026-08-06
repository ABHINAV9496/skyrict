import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  applySessionCookie,
  assertSameOrigin,
  backendError,
  callBackend,
  mapUser,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const mfaToken = typeof body.mfaToken === "string" ? body.mfaToken : "";
  const code = typeof body.code === "string" ? body.code.trim() : "";
  if (!mfaToken || !code) {
    return NextResponse.json({ error: "MFA token and code are required." }, { status: 400 });
  }

  const result = await callBackend("/auth/mfa/verify", {
    body: { mfa_token: mfaToken, code },
  });
  if (!result.ok) return backendError(result);

  const data = result.data;
  if (!data?.access_token) {
    return NextResponse.json({ error: "Unexpected verification response." }, { status: 502 });
  }

  const response = NextResponse.json({
    status: "authenticated",
    accessToken: data.access_token,
    expiresIn: data.expires_in ?? 0,
    user: mapUser(data.user as Record<string, unknown>),
  });
  if (data.refresh_token) applySessionCookie(response, String(data.refresh_token));
  return response;
}
