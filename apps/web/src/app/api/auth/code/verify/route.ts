import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  assertSameOrigin,
  backendError,
  callBackend,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const code = typeof body.code === "string" ? body.code.trim() : "";
  if (!email || !code) {
    return NextResponse.json({ error: "Email and code are required." }, { status: 400 });
  }

  const result = await callBackend("/auth/signup/verify-code", { body: { email, code } });
  if (!result.ok) return backendError(result);

  const data = result.data;
  return NextResponse.json({
    status: data?.status ?? "invalid",
    verificationToken: data?.verification_token ?? data?.verificationToken ?? null,
  });
}
