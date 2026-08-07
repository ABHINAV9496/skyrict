import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  assertSameOrigin,
  backendError,
  callBackend,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const result = await callBackend("/auth/signup/captcha", { method: "GET" });
  if (!result.ok) return backendError(result);
  return NextResponse.json(result.data);
}
