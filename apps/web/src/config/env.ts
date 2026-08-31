/**
 * Public (browser-safe) configuration.
 *
 * The browser never talks to the identity service directly, so there is no
 * public API base URL — all auth and onboarding traffic goes through the
 * same-origin /api/auth/* BFF route handlers.
 */
export const env = {
  turnstileSiteKey: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "",
  /**
   * Off by default (SKY-60 Q&A decision #5): when the supervisor stream
   * fails, the shell shows the error instead of fabricating a fake answer.
   * Set to "true" only in throwaway/dev environments to keep the UI usable
   * when the AI backend is down — never in production.
   */
  agentsSimulationEnabled: process.env.NEXT_PUBLIC_AGENTS_SIMULATION_ENABLED === "true",
};
