import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
    SESSION_COOKIE,
    applySessionCookie,
    callBackend,
    mapUser,
    resolveTenantSlug,
    rotateRefreshToken,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * Restore a session: refresh the access token from the httpOnly cookie, then
 * fetch the profile. The browser keeps the access token in memory; this route
 * re-hydrates it on page load and lets server components guard routes.
 */
export async function GET(request: NextRequest) {
    const refreshToken = request.cookies.get(SESSION_COOKIE)?.value;
    if (!refreshToken) {
        return NextResponse.json({ authenticated: false });
    }

    const slug = resolveTenantSlug(request.headers.get("host"));
    const rotated = await rotateRefreshToken(refreshToken, slug);
    if (!rotated.access) {
        const response = NextResponse.json({ authenticated: false });
        if (rotated.result.status === 401 || rotated.result.status === 0)
            applySessionCookie(response, null);
        return response;
    }

    const { token, refreshToken: rotatedToken, expiresIn } = rotated.access;

    const profile = await callBackend("/users/me", {
        method: "GET",
        token,
        tenantSlug: slug,
    });

    const response = NextResponse.json({
        authenticated: profile.ok,
        accessToken: profile.ok ? token : null,
        expiresIn,
        user: profile.ok ? mapUser(profile.data) : null,
    });
    if (profile.ok && rotatedToken) applySessionCookie(response, rotatedToken);
    return response;
}
