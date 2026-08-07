/**
 * Server-only (Node runtime) origin helpers.
 *
 * The workspace and signin surfaces live on different subdomains, so server
 * components and BFF redirects must build absolute cross-origin URLs from the
 * incoming Host header. Do not import this module from middleware (edge).
 */

import { headers } from "next/headers";

import { hostSurface, resolveTenantSlug } from "@/lib/server/auth";

interface OriginParts {
  proto: string;
  port: string;
  apex: string;
  host: string;
}

async function originParts(): Promise<OriginParts> {
  const h = await headers();
  const host = h.get("host") ?? "";
  const forwarded = h.get("x-forwarded-proto");
  const proto =
    forwarded?.split(",")[0]?.trim() ??
    (process.env.NODE_ENV === "production" ? "https" : "http");
  const hostname = host.replace(/:\d+$/, "").toLowerCase();
  const port = host.includes(":") ? `:${host.split(":").pop()}` : "";
  const apex = hostname.split(".").slice(1).join(".") || hostname;
  return { proto, port, apex, host };
}

/** Absolute `{slug}.signin.{apex}/signin` URL for the current tenant. */
export async function signinUrl(): Promise<string> {
  const { proto, port, apex, host } = await originParts();
  const { surface, slug } = hostSurface(host);
  if (surface === "signin") return `${proto}://${host}/signin`;
  const tenant = slug || resolveTenantSlug(host) || "app";
  return `${proto}://${tenant}.signin.${apex}${port}/signin`;
}

/** Absolute `{slug}.{apex}` origin for the current tenant. */
export async function workspaceUrl(): Promise<string> {
  const { proto, port, apex, host } = await originParts();
  const { surface, slug } = hostSurface(host);
  if (surface === "workspace") return `${proto}://${host}`;
  const tenant = slug || resolveTenantSlug(host) || "app";
  return `${proto}://${tenant}.${apex}${port}`;
}
