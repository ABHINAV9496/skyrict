import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { assertSameOrigin, backendError, callBackend } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * Pre-login signup plan catalog (SKY-36).
 *
 * The wizard Plan step runs before the owner has an account, so this proxies
 * the public backend catalog `GET /billing/signup/plans` (the same rows the
 * authenticated dashboard reads from `GET /billing/plans`). The server-side
 * catalog in `PLANS` is the single source of truth for plan pricing/features.
 */
export async function GET(request: NextRequest) {
    if (!assertSameOrigin(request)) {
        return NextResponse.json(
            { error: "Invalid request origin." },
            { status: 403 },
        );
    }

    const result = await callBackend("/billing/signup/plans", { method: "GET" });
    if (!result.ok) return backendError(result);

    const plans = Array.isArray(result.data)
        ? (result.data as unknown as Record<string, unknown>[])
        : [];
    return NextResponse.json({ data: plans });
}