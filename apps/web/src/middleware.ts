/**
 * Host-based routing for the four subdomain surfaces.
 *
 * One Next app serves every surface; the Host header picks which one. The
 * middleware resolves the surface + tenant slug (mirroring the backend
 * TenantResolver), rejects unknown hosts, and rewrites public paths to their
 * internal routes:
 *
 *   marketing  web.localhost            `/`            → landing (register-only)
 *   signup     signup.localhost         `/signup`      → `/register`
 *   signin     {slug}.signin.localhost  `/signin`      → `/login`
 *   workspace  {slug}.localhost         `/`, `/agents` → `/dashboard/…`
 *
 * Public URLs never contain `/dashboard` or `signin`; the internal
 * `/dashboard/*` tree is the workspace app, served at the tenant root.
 */

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { hostSurface } from "@/lib/server/auth";

const AUTH_PATHS = [
  "/login",
  "/register",
  "/setup-mfa",
  "/signin",
  "/signup",
  "/invite",
  "/forgot-password",
  "/reset-password",
];

function isAuthPath(pathname: string): boolean {
  return (
    AUTH_PATHS.includes(pathname) ||
    pathname.startsWith("/register/") ||
    pathname.startsWith("/mfa/")
  );
}

function baseParts(request: NextRequest): { protocol: string; port: string; apex: string } {
  const { protocol, hostname, port } = request.nextUrl;
  const apex = hostname.split(".").slice(1).join(".") || hostname;
  return { protocol, port: port ? `:${port}` : "", apex };
}

function signupOrigin(request: NextRequest): string {
  const { protocol, port, apex } = baseParts(request);
  return `${protocol}//signup.${apex}${port}/signup`;
}

function signinOrigin(request: NextRequest, slug: string): string {
  const { protocol, port, apex } = baseParts(request);
  return `${protocol}//${slug}.signin.${apex}${port}/signin`;
}

function notFound(): NextResponse {
  return NextResponse.rewrite(new URL("/_not-found", "http://internal.localhost"));
}

export function middleware(request: NextRequest) {
  const host = request.headers.get("host") ?? "";
  const { surface, slug } = hostSurface(host);
  const { pathname } = request.nextUrl;

  const isApi = pathname.startsWith("/api");
  const isStatic = pathname.startsWith("/_next") || pathname === "/favicon.ico";

  if (isStatic) return NextResponse.next();

  if (surface === "unknown") {
    if (isApi) return NextResponse.json({ error: "Not found." }, { status: 404 });
    return notFound();
  }

  if (isApi) return NextResponse.next();

  switch (surface) {
    case "marketing": {
      // Register-only marketing site: auth paths leave via the signup origin.
      if (isAuthPath(pathname) || pathname.startsWith("/dashboard")) {
        return NextResponse.redirect(new URL(signupOrigin(request), request.url));
      }
      return NextResponse.next();
    }
    case "signup": {
      if (pathname === "/signup") {
        return NextResponse.rewrite(new URL("/register", request.url));
      }
      if (isAuthPath(pathname)) {
        return NextResponse.next();
      }
      return NextResponse.redirect(new URL("/signup", request.url));
    }
    case "signin": {
      if (pathname === "/signin") {
        return NextResponse.rewrite(new URL("/login", request.url));
      }
      if (pathname === "/setup-mfa" || pathname === "/mfa/verify") {
        return NextResponse.next();
      }
      return NextResponse.redirect(new URL("/signin", request.url));
    }
    case "workspace": {
      if (isAuthPath(pathname)) {
        return NextResponse.redirect(new URL(signinOrigin(request, slug), request.url));
      }
      if (pathname === "/dashboard") {
        return NextResponse.redirect(new URL("/", request.url));
      }
      if (pathname.startsWith("/dashboard/")) {
        return NextResponse.redirect(
          new URL(pathname.slice("/dashboard".length), request.url),
        );
      }
      const internal = pathname === "/" ? "/dashboard" : `/dashboard${pathname}`;
      return NextResponse.rewrite(new URL(internal, request.url));
    }
    default:
      return notFound();
  }
}

export const config = {
  // Skip Next-managed static assets and anything with a file extension.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\..*).*)"],
};
