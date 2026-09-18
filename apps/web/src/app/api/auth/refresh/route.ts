import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
    SESSION_COOKIE,
    applySessionCookie,
    backendError,
    resolveTenantSlug,
    rotateRefreshToken,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/** Silent refresh: rotate the httpOnly cookie and return a fresh access token. */
export async function POST(request: NextRequest) {
    const refreshToken = request.cookies.get(SESSION_COOKIE)?.value;
    if (!refreshToken) {
        return NextResponse.json(
            { status: "unauthenticated" },
            { status: 401 },
        );
    }

    const slug = resolveTenantSlug(request.headers.get("host"));
    const rotated = await rotateRefreshToken(refreshToken, slug);
    const result = rotated.result;
    if (!rotated.access) {
        if (result.status === 401 || result.status === 0) {
            const clear = NextResponse.json(
                { status: "unauthenticated" },
                { status: 401 },
            );
            applySessionCookie(clear, null);
            return clear;
        }
        return backendError(result);
    }

    const response = NextResponse.json({
        status: "authenticated",
        accessToken: rotated.access.token,
        expiresIn: rotated.access.expiresIn,
    });
    if (rotated.access.refreshToken)
        applySessionCookie(response, rotated.access.refreshToken);
    return response;
}
