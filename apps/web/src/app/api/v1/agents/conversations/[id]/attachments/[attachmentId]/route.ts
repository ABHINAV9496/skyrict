import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
    assertSameOrigin,
    callBackendStream,
    resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * BFF relay for conversation attachment blobs (SKY-60 attachment durability).
 *
 * The GET fetch is made with an in-memory Bearer token (never a cookie), so a
 * direct `<img src>` to the BFF cannot authenticate - the frontend fetches the
 * blob via `apiFetchRaw` and previews it through an object URL, exactly like
 * document detail previews. This route shadows the `/api/v1/[...path]`
 * catch-all so the binary body passes through untouched instead of being
 * round-tripped as JSON.
 */
export async function GET(
    request: NextRequest,
    {
        params,
    }: { params: Promise<{ id: string; attachmentId: string }> },
) {
    if (!assertSameOrigin(request)) {
        return NextResponse.json(
            { error: "Invalid request origin." },
            { status: 403 },
        );
    }

    const { id, attachmentId } = await params;
    const slug = resolveTenantSlug(request.headers.get("host"));
    const authorization = request.headers.get("authorization");
    const token = authorization?.toLowerCase().startsWith("bearer ")
        ? authorization.slice("Bearer ".length)
        : null;

    const upstream = await callBackendStream(
        `/ai/agents/conversations/${encodeURIComponent(id)}/attachments/${encodeURIComponent(attachmentId)}`,
        { method: "GET", tenantSlug: slug, token, target: "core" },
    );

    if (!upstream || !upstream.body) {
        return NextResponse.json(
            { detail: "Core service is unavailable. Please try again." },
            { status: 502 },
        );
    }

    const headers = new Headers();
    for (const name of ["Content-Type", "Content-Disposition"]) {
        const value = upstream.headers.get(name);
        if (value) headers.set(name, value);
    }
    if (!headers.has("Content-Type")) {
        headers.set("Content-Type", "application/octet-stream");
    }
    return new Response(upstream.body, {
        status: upstream.status,
        headers,
    });
}