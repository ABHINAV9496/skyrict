/**
 * Client-side URL helpers mirroring the middleware's cross-surface routing.
 * Kept free of React so any browser module (session provider, API client) can
 * compute the tenant signin origin without a circular import.
 */

/**
 * Absolute `{slug}.signin.{apex}:{port}/signin` URL for the current origin,
 * mirroring the middleware's cross-surface routing. Falls back to the current
 * origin's `/signin` when there is no tenant label (dev without a subdomain).
 */
export function browserSigninUrl(): string {
  const { protocol, hostname, port } = window.location;
  const host = hostname.toLowerCase();
  const portSuffix = port ? `:${port}` : "";
  if (host.includes(".signin.")) return `${protocol}//${host}${portSuffix}/signin`;
  const apex = host.split(".").slice(1).join(".");
  if (!apex) return `${protocol}//${host}${portSuffix}/signin`;
  const slug = host.split(".")[0];
  return `${protocol}//${slug}.signin.${apex}${portSuffix}/signin`;
}
