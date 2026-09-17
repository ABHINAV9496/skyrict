/*
 * Surface URL builders for the multi-tenant E2E harness.
 *
 * The app serves four subdomain surfaces (see apps/web/src/middleware.ts):
 * marketing (localhost), signup (signup.localhost), signin
 * ({slug}.signin.localhost) and workspace ({slug}.localhost). In CI the
 * browser reaches all of them through nginx on the E2E origin
 * (E2E_BASE_URL, default http://default.localhost:3000), which injects the
 * tenant slug from the subdomain.
 *
 * Every builder derives the apex and port from E2E_BASE_URL so an
 * overridden stack (different port or apex) stays consistent with the
 * origin Playwright actually navigates.
 */

type Surface = "workspace" | "signin" | "signup" | "marketing";

const DEFAULT_E2E_BASE_URL = "http://default.localhost:3000";

function surfaceBase(surface: Surface, slug = ""): string {
  const url = new URL(process.env.E2E_BASE_URL ?? DEFAULT_E2E_BASE_URL);
  const parts = url.hostname.split(".").filter(Boolean);
  // E2E_BASE_URL is a tenanted origin ({slug}.{apex}, e.g. default.localhost),
  // so drop exactly the leading tenant label to recover the apex. Works for
  // bare localhost too (parts.length < 2).
  const apex = parts.length >= 2 ? parts.slice(1).join(".") : url.hostname;
  const port = url.port ? `:${url.port}` : "";
  const host =
    surface === "workspace"
      ? `${slug}.${apex}`
      : surface === "signin"
        ? `${slug}.signin.${apex}`
        : surface === "signup"
          ? `signup.${apex}`
          : apex;
  return `${url.protocol}//${host}${port}`;
}

/** http://{slug}.localhost:3000 - workspace surface for a tenant. */
export function workspaceUrl(slug: string): string {
  return surfaceBase("workspace", slug);
}

/** http://{slug}.signin.localhost:3000 - sign-in surface for a tenant. */
export function signinUrl(slug: string): string {
  return surfaceBase("signin", slug);
}

/** http://signup.localhost:3000 - self-service onboarding surface. */
export function signupUrl(): string {
  return surfaceBase("signup");
}

/** http://localhost:3000 - public marketing surface. */
export function marketingUrl(): string {
  return surfaceBase("marketing");
}