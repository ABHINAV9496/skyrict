import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { assertSameOrigin, callBackend, resolveTenantSlug } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const result = await callBackend("/ai/agents/conversations", {
    method: "GET",
    tenantSlug: slug,
    token: extractToken(request),
    target: "core",
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.payload?.detail ?? "Failed to load conversations." },
      { status: result.status },
    );
  }
  return NextResponse.json({ data: result.data });
}

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const body = await request.json().catch(() => ({}));

  const result = await callBackend("/ai/agents/conversations", {
    method: "POST",
    body,
    tenantSlug: slug,
    token: extractToken(request),
    target: "core",
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.payload?.detail ?? "Failed to create conversation." },
      { status: result.status },
    );
  }
  return NextResponse.json({ data: result.data }, { status: 201 });
}

function extractToken(request: NextRequest): string | null {
  const authorization = request.headers.get("authorization");
  return authorization?.toLowerCase().startsWith("bearer ")
    ? authorization.slice("Bearer ".length)
    : null;
}
