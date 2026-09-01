import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { assertSameOrigin, callBackendStream, resolveTenantSlug } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * BFF relay for the supervisor SSE chat stream (SKY-60).
 *
 * This static route shadows the ``/api/v1/[...path]`` catch-all for the
 * streaming endpoint: instead of buffering the JSON body it relays the core
 * monolith's ``text/event-stream`` response chunk-by-chunk, so the Agents
 * shell renders tokens live.
 *
 * The same BFF guardrails apply as the catch-all: the tenant slug is derived
 * server-side from the Host header, the client's Bearer access token is
 * forwarded verbatim (core re-verifies it and ai-agent binds every delegated
 * read to that caller), and the POST must pass the Origin/Referer CSRF gate.
 */
export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const slug = resolveTenantSlug(request.headers.get("host"));
  const authorization = request.headers.get("authorization");
  const token = authorization?.toLowerCase().startsWith("bearer ")
    ? authorization.slice("Bearer ".length)
    : null;
  const body = await request.json().catch(() => undefined);

  const upstream = await callBackendStream("/ai/agents/chat/stream", {
    method: "POST",
    body,
    tenantSlug: slug,
    token,
    target: "core",
  });

  if (!upstream || !upstream.body) {
    return NextResponse.json(
      { detail: "Core service is unavailable. Please try again." },
      { status: 502 },
    );
  }

  // Only the SSE content type and the no-buffering hints survive; the
  // upstream body is handed to the browser as a live stream.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  });
}