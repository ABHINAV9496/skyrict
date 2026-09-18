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
export async function fillOtp(
    page: Page,
    label: string,
    code: string,
): Promise<void> {
    for (let i = 0; i < code.length; i += 1) {
        await page
            .locator(`input[aria-label="${label} digit ${i + 1}"]`)
            .fill(code[i]!);
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
export async function whichMfaPath(
    page: Page,
    timeoutMs = 15_000,
): Promise<MfaPath> {
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
export async function completeMfaChallenge(
    page: Page,
    secret: string,
): Promise<void> {
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
        const body = (await response.json().catch(() => ({}))) as Record<
            string,
            unknown
        >;
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
        .getByRole("button", {
            name: "I've saved my recovery codes somewhere safe.",
        })
        .click();
    await page.getByRole("button", { name: "Finish setup" }).click();
    await waitForWorkspace(page);
    return secret;
}

/** Wait for the login/MFA handoff to land on the workspace host. */
export async function waitForWorkspace(page: Page): Promise<void> {
    await page.waitForURL((url) => !url.hostname.includes(".signin."), {
        timeout: 20_000,
    });
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
 * Verify the authenticated session actually authenticates BFF calls before a
 * fixture yields the workspace.
 *
 * The sidebar email only proves the shell hydrated once from a refresh
 * cookie; it says nothing about whether the BFF can forward the session
 * downstream when the browser only sends cookies (no in-memory access token).
 * Hit the identity current-user endpoint through the BFF and require 200:
 * when this fails, every suite would otherwise drown in opaque
 * ``401 Missing Authorization header`` errors from raw page.evaluate fetches.
 *
 * The probe rotates the refresh token once through the BFF - safe here
 * because it runs after waitForWorkspaceSettled() left the shell idle, so it
 * cannot race the app's own single-flight rotation.
 */
export async function assertSessionReachesBff(page: Page): Promise<void> {
  const probe = await page.evaluate(async () => {
    const res = await fetch("/api/v1/users/me", {
      credentials: "include",
      cache: "no-store",
    });
    let body = "";
    try {
      body = (await res.text()).slice(0, 240);
    } catch {
      // keep the body empty when the stream cannot be read
    }
    return { status: res.status, body };
  });
  expect(
    probe.status,
    `BFF session probe to /api/v1/users/me did not authenticate: ` +
      `HTTP ${probe.status} ${probe.body}`,
  ).toBe(200);
}

/**
 * Wait for the workspace shell to finish its initial session hydration.
 *
 * The logo link ("Skyrict dashboard") is part of the SERVER-rendered shell and
 * appears as soon as a session cookie exists - long before the client's
 * SessionProvider.restore() finishes rotating the refresh token on mount.
 * Resolving on the link alone lets the test's first goto abort that in-flight
 * hydration: the backend completes the rotation (advancing the session's token
 * hash) while the browser, whose fetch the navigation killed, never stores the
 * new Set-Cookie. The next page then presents a stale token, the backend's
 * reuse detector revokes the whole session family, and the user is bounced to
 * /signin (see reports-workspace.spec.ts; proven via the identity audit log:
 * auth.refresh.success immediately followed by auth.refresh.reuse_detected).
 *
 * The real readiness signal is the sidebar user menu: it renders the signed-in
 * user's email only after restore() resolves - i.e. the BFF session restore
 * completed AND its Set-Cookie was applied to the cookie jar. Waiting on that
 * after the shell link means the test's first navigation always starts from a
 * settled, current session.
 *
 * Do NOT attach a 401 auto-refresh here: the app's own single-flight recovery
 * (lib/api/http.ts ensureSession) is the only sanctioned rotation source - a
 * parallel /api/auth/session from the harness would race it and revoke the
 * whole token family.
 */
export async function waitForWorkspaceSettled(page: Page, email?: string): Promise<void> {
  await expect(
    page.getByRole("link", { name: "Skyrict dashboard", exact: true }),
  ).toBeVisible({ timeout: 20_000 });
  const expected = email ?? process.env.E2E_ADMIN_EMAIL ?? "admin@skyrict.io";
  await expect(
    page.getByText(expected, { exact: true }).first(),
    "sidebar user menu must render the signed-in user's email after session hydration",
  ).toBeVisible({ timeout: 20_000 });
}

/**
 * First sign-in of a freshly registered tenant owner: mandatory MFA takes the
 * enrollment path (/setup-mfa) because a brand-new account has no authenticator
 * enrolled. Attaches the secret capture BEFORE the BFF login handoff (the setup
 * page calls the API on mount), signs in, asserts the enrollment path, and
 * completes it. Returns the captured TOTP secret so the caller can later play
 * the challenge leg.
 */
export async function firstOwnerSignInAndEnrollMfa(
    page: Page,
    email: string,
    password: string,
): Promise<string> {
    const getMfaSecret = installMfaSecretCapture(page);
    await signInWithPassword(page, email, password);
    expect(await whichMfaPath(page)).toBe("enrollment");
    return enrollMfaAndFinish(page, { secretGetter: getMfaSecret });
}
