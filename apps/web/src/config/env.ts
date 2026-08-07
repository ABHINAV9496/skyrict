/**
 * Public (browser-safe) configuration.
 *
 * The browser never talks to the identity service directly, so there is no
 * public API base URL — all auth and onboarding traffic goes through the
 * same-origin /api/auth/* BFF route handlers.
 */
export const env = {
  turnstileSiteKey: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "",
};
