/*
 * Shared authentication flow primitives for the multi-tenant E2E harness.
 *
 * Centralizes the sign-in form flow, the mandatory-MFA enrollment and challenge
 * paths, the TOTP fill helper, and the persisted-secret reader so the setup
 * project, the worker-scoped auth fixture, and the tenant fixture all walk the
 * same flows against the same components.
 *
 * Every helper drives the real BFF (/api/auth/*) and the signin surface - no
 * direct identity calls, no bypassed CSRF, no mock storage.
 */

import { readFileSync } from "node:fs";

import { expect, type Page } from "@playwright/test";

import { totp } from "./totp";

export const TOTP_SECRET_FILE = "e2e/.auth/totp-secret";

/** The enrolled TOTP secret: env override wins, else the persisted file. */
export function readEnrolledSecret(secretFile = TOTP_SECRET_FILE): string {
  const fromEnv = process.env.E2E_TOTP_SECRET;
  if (fromEnv) return fromEnv;
  try {
    return readFileSync(secretFile, "utf8").trim();
  } catch {
    return "";
  }
}

/** Fill each OtpInput digit box (aria-label "<label> digit N"). */
export async function fillOtp(page: Page, label: string, code: string): Promise<void> {
  for (let i = 0; i < code.length; i += 1) {
    await page.locator(`input[aria-label="${label} digit ${i + 1}"]`).fill(code[i]!);
  }
}

/**
 * Submit the sign-in form on the signin surface. The page must already be on
 * {slug}.signin.{apex}/signin; email is always re-filled because the signin
 * surface's auto-completed email would otherwise be stale.
 */
export async function signInWithPassword(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

export type MfaPath = "enrollment" | "challenge";

/**
 * Detect which mandatory-MFA path the sign-in flow takes: the account either
 * lands on /setup-mfa (first enrollment) or is challenged for a TOTP code on
 * the login form (already enrolled). Fighting over the same timer is the
 * established pattern - both waits observe the same page and the winner
 * resolves first.
 */
export async function whichMfaPath(page: Page, timeoutMs = 15_000): Promise<MfaPath> {
  return new Promise<MfaPath>((resolve) => {
    void page
      .waitForURL("**/setup-mfa", { timeout: timeoutMs })
      .then(() => resolve("enrollment"))
      .catch(() => {});
    void page
      .getByRole("heading", { name: "Two-factor check" })
      .waitFor({ timeout: timeoutMs })
      .then(() => resolve("challenge"))
      .catch(() => {});
  });
}

/**
 * Complete the TOTP challenge on the login form and wait for the handoff to
 * the workspace host. The OTP form submits itself as soon as the last digit is
 * filled, so no click is needed - and none is safe (the button is mid-flight
 * disabled).
 */
export async function completeMfaChallenge(page: Page, secret: string): Promise<void> {
  await fillOtp(page, "Two-factor code", totp(secret));
  await waitForWorkspace(page);
}

/**
 * Capture the raw TOTP secret the browser receives from the MFA setup API.
 * Attach BEFORE navigating to /setup-mfa - the setup page calls the API on
 * mount, so a late listener would miss the only response that carries the
 * secret. A response listener is used instead of route interception because
 * route.fetch() re-issues the request through Node, which cannot resolve the
 * *.localhost host (only the browser can).
 *
 * Returns a getter that reflects the latest captured value (or null before the
 * response lands).
 */
export function installMfaSecretCapture(page: Page): () => string | null {
  let mfaSecret: string | null = null;
  page.on("response", async (response) => {
    if (!response.url().includes("/api/auth/mfa/setup")) return;
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    mfaSecret = typeof body.secret === "string" ? body.secret : null;
  });
  return () => mfaSecret;
}

/**
 * Complete mandatory MFA enrollment on /setup-mfa: wait for (or reuse) the
 * TOTP secret, verify a code generated from it, acknowledge the recovery
 * codes, finish setup, and wait for the handoff to the workspace host.
 *
 * Callers pass a `secretGetter` from installMfaSecretCapture() when the secret
 * is unknown ahead of time, and/or a `knownSecret` fallback (e.g. the
 * persisted secret from a previous run). `onWritten` is invoked with the
 * resolved secret BEFORE the TOTP loop so a clock-boundary failure still
 * leaves a recoverable secret. Returns the resolved secret.
 */
export async function enrollMfaAndFinish(
  page: Page,
  options: {
    secretGetter?: () => string | null;
    knownSecret?: string;
    onWritten?: (secret: string) => void;
  } = {},
): Promise<string> {
  if (options.secretGetter) {
    await expect
      .poll(() => options.secretGetter?.() ?? null, {
        timeout: 10_000,
        message: "MFA setup response did not include a TOTP secret.",
      })
      .toBeTruthy();
  }

  const secret = options.secretGetter?.() ?? options.knownSecret ?? "";
  expect(secret, "MFA setup secret is missing.").toBeTruthy();
  options.onWritten?.(secret);

  // Verify a TOTP code generated from the secret. Try the current, previous,
  // and next 30s windows to dodge clock boundaries.
  let verified = false;
  for (const offset of [0, -1, 1]) {
    await fillOtp(page, "Authenticator code", totp(secret, offset));
    await page.getByRole("button", { name: "Verify and continue" }).click();

    const success = page
      .getByText("Authenticator verified")
      .waitFor({ timeout: 4_000 })
      .then(() => true)
      .catch(() => false);
    const failure = page
      .getByText("That code doesn't match")
      .waitFor({ timeout: 4_000 })
      .then(() => false)
      .catch(() => false);
    if (await Promise.race([success, failure])) {
      verified = true;
      break;
    }
  }
  expect(
    verified,
    "TOTP enrollment failed across the current, previous, and next windows.",
  ).toBe(true);

  // Acknowledge and finish; the handoff form-POSTs to the workspace origin
  // and lands on {slug}.localhost (never the signin host).
  await page
    .getByRole("button", { name: "I've saved my recovery codes somewhere safe." })
    .click();
  await page.getByRole("button", { name: "Finish setup" }).click();
  await waitForWorkspace(page);
  return secret;
}

/** Wait for the login/MFA handoff to land on the workspace host. */
export async function waitForWorkspace(page: Page): Promise<void> {
  await page.waitForURL(
    (url) => !url.hostname.includes(".signin."),
    { timeout: 20_000 },
  );
}

/**
 * Re-hydrate the session exactly like the app's own navigation does: a
 * same-origin GET through the BFF rotates the refresh token and the browser
 * stores the new Set-Cookie in its jar. This MUST run in the browser context
 * (page.evaluate) - Playwright's APIRequestContext resolves hostnames through
 * Node, which cannot resolve *.localhost, and issuing the request from the
 * default-origin page would dereference a tenant that does not exist.
 */
export async function refreshSession(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const res = await fetch("/api/auth/session", {
      credentials: "include",
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Session refresh failed: HTTP ${res.status}`);
    }
  });
}

/**
 * Auto-refresh the session through the BFF whenever a backend API answers 401,
 * so the next navigation always presents the current (un-rotated) token.
 * Attach AFTER the workspace has landed - the sign-in handshake itself can
 * legitimately produce 401-like flows that must not rotate the session.
 */
export function installSessionRefresh(page: Page): void {
  page.on("response", (response) => {
    if (response.status() === 401 && response.url().includes("/api/v1/")) {
      void refreshSession(page).catch(() => {});
    }
  });
}