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
  const verificationToken =
    typeof body.verificationToken === "string" ? body.verificationToken : "";
  const password = typeof body.password === "string" ? body.password : "";
  if (!email || !verificationToken || !password) {
    return NextResponse.json(
      { error: "Email, verification token, and password are required." },
      { status: 400 },
    );
  }

  const result = await callBackend("/auth/signup/password", {
    body: { email, verification_token: verificationToken, password },
  });
  if (!result.ok) return backendError(result);
  return NextResponse.json({ status: "ok" });
}
