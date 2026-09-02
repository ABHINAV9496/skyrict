import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { assertSameOrigin, callBackend, resolveTenantSlug } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

function extractToken(request: NextRequest): string | null {
  const authorization = request.headers.get("authorization");
  return authorization?.toLowerCase().startsWith("bearer ")
    ? authorization.slice("Bearer ".length)
    : null;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const { id } = await params;
  const slug = resolveTenantSlug(request.headers.get("host"));

  const result = await callBackend(`/ai/agents/conversations/${id}`, {
    method: "GET",
    tenantSlug: slug,
    token: extractToken(request),
    target: "core",
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.payload?.detail ?? "Conversation not found." },
      { status: result.status },
    );
  }
  return NextResponse.json({ data: result.data });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const { id } = await params;
  const slug = resolveTenantSlug(request.headers.get("host"));
  const body = await request.json().catch(() => ({}));

  const result = await callBackend(`/ai/agents/conversations/${id}`, {
    method: "POST",
    body,
    tenantSlug: slug,
    token: extractToken(request),
    target: "core",
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.payload?.detail ?? "Failed to append message." },
      { status: result.status },
    );
  }
  return NextResponse.json({ data: result.data }, { status: 201 });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const { id } = await params;
  const slug = resolveTenantSlug(request.headers.get("host"));
  const body = await request.json().catch(() => ({}));

  const result = await callBackend(`/ai/agents/conversations/${id}`, {
    method: "PATCH",
    body,
    tenantSlug: slug,
    token: extractToken(request),
    target: "core",
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.payload?.detail ?? "Failed to update conversation." },
      { status: result.status },
    );
  }
  return NextResponse.json({ data: result.data });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const { id } = await params;
  const slug = resolveTenantSlug(request.headers.get("host"));

  const result = await callBackend(`/ai/agents/conversations/${id}`, {
    method: "DELETE",
    tenantSlug: slug,
    token: extractToken(request),
    target: "core",
  });

  if (!result.ok) {
    return NextResponse.json(
      { detail: result.payload?.detail ?? "Failed to delete conversation." },
      { status: result.status },
    );
  }
  return NextResponse.json({ data: { deleted: true } });
}
