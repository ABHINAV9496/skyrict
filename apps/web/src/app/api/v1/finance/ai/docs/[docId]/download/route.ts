import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { callBackendStream, resolveTenantSlug } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * BFF relay for AI document pack downloads (FIN-AI-004).
 *
 * This static route shadows the ``/api/v1/[...path]`` catch-all for the PDF
 * download: ``callBackend``'s JSON buffer would turn the PDF bytes into ``{}``
 * (the same corruption the reports CSV export route fixes), so the upstream
 * ``application/pdf`` body is passed to the browser as-is. Only the
 * download-relevant headers survive, mirroring the stream/attach relays.
 */
export async function GET(
    request: NextRequest,
    { params }: { params: Promise<{ docId: string }> },
) {
    const { docId } = await params;
    const slug = resolveTenantSlug(request.headers.get("host"));
    const authorization = request.headers.get("authorization");
    const token = authorization?.toLowerCase().startsWith("bearer ")
        ? authorization.slice("Bearer ".length)
        : null;

    const upstream = await callBackendStream(
        `/finance/ai/docs/${encodeURIComponent(docId)}/download`,
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
    return new Response(upstream.body, { status: upstream.status, headers });
}
