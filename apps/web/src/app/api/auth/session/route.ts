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
    // Identity rotates the refresh token unconditionally on /auth/refresh, so
    // always write the rotated cookie back - even when the /users/me probe
    // transiently fails. Otherwise the browser keeps presenting an already-
    // spent value, and a second failed probe leaves it TWO generations behind
    // the session record, which identity's reuse check treats as a family
    // revoke - taking down every subsequent authenticated call with the
    // generic "Missing Authorization header" 401.
    if (rotatedToken) applySessionCookie(response, rotatedToken);
    return response;
}
