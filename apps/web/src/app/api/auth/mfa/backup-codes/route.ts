import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import {
  assertSameOrigin,
  backendError,
  callBackend,
  resolveTenantSlug,
} from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!assertSameOrigin(request)) {
    return NextResponse.json({ error: "Invalid request origin." }, { status: 403 });
  }

  const authHeader = request.headers.get("authorization") ?? "";
  const token = authHeader.startsWith("Bearer ") ? authHeader.slice("Bearer ".length) : "";
  if (!token) {
    return NextResponse.json({ error: "Session expired." }, { status: 401 });
  }

  const result = await callBackend("/mfa/backup-codes", {
    token,
    tenantSlug: resolveTenantSlug(request.headers.get("host")),
  });
  if (!result.ok) return backendError(result);

  const data = result.data;
  return NextResponse.json({
    backup_codes: Array.isArray(data?.backup_codes)
      ? (data.backup_codes as string[])
      : [],
  });
}
