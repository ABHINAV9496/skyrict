import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  assertSameOrigin,
  backendError,
  callBackend,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const body = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const verificationToken =
    typeof body.verificationToken === "string" ? body.verificationToken : "";
  const planId = typeof body.planId === "string" ? body.planId : "";
  const companyName = typeof body.companyName === "string" ? body.companyName.trim() : "";
  const industry = typeof body.industry === "string" ? body.industry.trim() : "";
  const workspaceSlug = typeof body.workspaceSlug === "string" ? body.workspaceSlug.trim() : "";
  const ownerFullName = typeof body.ownerFullName === "string" ? body.ownerFullName.trim() : "";

  if (!email || !verificationToken || !planId || !companyName || !workspaceSlug || !ownerFullName) {
    return NextResponse.json(
      { error: "Missing required organization fields." },
      { status: 400 },
    );
  }

  const result = await callBackend("/auth/signup/organization", {
    body: {
      email,
      verificationToken,
      planId,
      companyName,
      industry,
      workspaceSlug,
      ownerFullName,
      phoneCountry: body.phoneCountry ?? null,
      phoneNumber: body.phoneNumber ?? null,
      address: body.address ?? null,
    },
  });
  if (!result.ok) return backendError(result);

  const data = result.data;
  return NextResponse.json({
    status: data?.status ?? "ok",
    mfaRequired: Boolean(data?.mfa_required ?? data?.mfaRequired ?? true),
    tenantId: data?.tenant_id ?? data?.tenantId ?? null,
    tenantSlug: data?.tenant_slug ?? data?.tenantSlug ?? workspaceSlug,
  });
}
