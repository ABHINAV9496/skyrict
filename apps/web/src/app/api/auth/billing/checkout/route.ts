import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
    assertSameOrigin,
    backendError,
    callBackend,
    clientIp,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * Pre-login Stripe Checkout session for the wizard Billing step (SKY-36).
 *
 * The owner has not logged in yet, so authorization is the verification token
 * bound to the signup email plus membership in the provisioned tenant (the
 * backend re-validates both). Returns the Stripe `url` the browser should
 * redirect to; paid plans stay `trialing` server-side until the real
 * subscription webhook fires.
 */
export async function POST(request: NextRequest) {
    if (!assertSameOrigin(request)) {
        return NextResponse.json(
            { error: "Invalid request origin." },
            { status: 403 },
        );
    }

    const body = (await request.json().catch(() => ({}))) as Record<
        string,
        unknown
    >;
    const email =
        typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
    const verificationToken =
        typeof body.verificationToken === "string"
            ? body.verificationToken
            : "";
    const tenantId =
        typeof body.tenantId === "string" ? body.tenantId.trim() : "";
    const planId = typeof body.planId === "string" ? body.planId : "";
    const interval =
        typeof body.interval === "string" ? body.interval : "month";
    const currency =
        typeof body.currency === "string"
            ? body.currency.trim().toLowerCase()
            : "usd";

    if (!email || !verificationToken || !tenantId || !planId) {
        return NextResponse.json(
            { error: "Missing required checkout fields." },
            { status: 400 },
        );
    }
    if (interval !== "month" && interval !== "year") {
        return NextResponse.json(
            { error: "Invalid billing interval." },
            { status: 400 },
        );
    }
    if (
        currency !== "usd" &&
        currency !== "inr" &&
        currency !== "gbp" &&
        currency !== "eur"
    ) {
        return NextResponse.json(
            { error: "Invalid currency." },
            { status: 400 },
        );
    }

    const result = await callBackend("/auth/signup/checkout-session", {
        body: {
            email,
            verificationToken,
            tenantId,
            planId,
            interval,
            currency,
        },
        userAgent: request.headers.get("user-agent"),
        clientIp: clientIp(request),
    });
    if (!result.ok) return backendError(result);

    const data = result.data;
    return NextResponse.json({
        session_id: data?.session_id ?? "",
        url: data?.url ?? "",
    });
}
