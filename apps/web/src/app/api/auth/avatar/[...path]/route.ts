import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { apiBase, resolveTenantSlug } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/**
 * Serve an avatar image as raw bytes.
 *
 * The avatar endpoints are deliberately unauthenticated (`<img>` tags cannot
 * send Authorization headers), so this route just validates the path shape,
 * resolves the tenant slug from the Host header (mirroring the backend
 * TenantResolver), and proxies the bytes. The filenames are server-generated
 * UUIDs and the storage is tenant-scoped, so the URL itself is not guessable
 * outside its tenant. The generic /api/v1 proxy cannot be used here because it
 * wraps responses in JSON - this route passes the binary body straight through.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FILENAME_RE = /^[a-f0-9]{32}\.webp$/;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const slug = resolveTenantSlug(request.headers.get("host"));
  if (!slug) return new NextResponse(null, { status: 404 });

  const segments = (await params).path;
  const [userId, filename] = segments;
  if (
    segments.length !== 2 ||
    !UUID_RE.test(userId ?? "") ||
    !FILENAME_RE.test(filename ?? "")
  ) {
    return new NextResponse(null, { status: 404 });
  }

  let response: Response;
  try {
    response = await fetch(
      `${apiBase()}/api/v1/avatars/${encodeURIComponent(userId)}/${encodeURIComponent(filename)}`,
      { headers: { "X-Tenant-Slug": slug }, cache: "no-store" },
    );
  } catch {
    return new NextResponse(null, { status: 404 });
  }

  if (!response.ok) return new NextResponse(null, { status: response.status });

  const bytes = new Uint8Array(await response.arrayBuffer());
  return new NextResponse(bytes, {
    status: 200,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "image/webp",
      "Content-Length": String(bytes.byteLength),
      "Cache-Control": "public, max-age=31536000, immutable",
    },
  });
}
