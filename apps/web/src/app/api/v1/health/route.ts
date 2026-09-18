import { NextResponse } from "next/server";

/**
 * Liveness probe for the Next.js process itself.
 *
 * Served directly by Next with no backend, auth, or tenant dependency so CI
 * (e2e.yml "Start Next.js" step) can verify the web server accepts requests
 * independently of the compose services. A static segment takes precedence
 * over the `/api/v1/[...path]` BFF catch-all, so this never proxies to a
 * backend and never requires a session cookie (the catch-all would otherwise
 * answer 401 - Missing Authorization header - and block the readiness probe).
 */
export function GET() {
  return NextResponse.json({ status: "healthy", service: "web" }, { status: 200 });
}