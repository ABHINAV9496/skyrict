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
  const slug = typeof body.slug === "string" ? body.slug.trim() : "";
  if (!slug) {
    return NextResponse.json({ error: "Slug is required." }, { status: 400 });
  }

  const result = await callBackend("/auth/signup/check-slug", { body: { slug } });
  if (!result.ok) return backendError(result);

  return NextResponse.json({ available: Boolean(result.data?.available) });
}
