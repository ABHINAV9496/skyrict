/*
 * Playwright auth setup for the multi-tenant E2E harness.
 *
 * Signs in as the seeded admin (admin@skyrict.io / Admin123! by default,
 * overridable via E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD) and completes the
 * mandatory MFA enrollment by capturing the TOTP secret from the browser's
 * setup-MFA API response. Saves the authenticated storage state so the
 * suite's tests start logged in.
 *
 * The first run takes the enrollment path (/setup-mfa). If the admin already
 * has MFA enabled, the challenge path is taken instead and requires
 * E2E_TOTP_SECRET. Flow primitives are shared with the worker-scoped fixtures
 * (see e2e/helpers/auth-flow.ts).
 */

import { mkdirSync, writeFileSync } from "node:fs";

import { expect, test as setup, type Page } from "@playwright/test";

import {
    TOTP_SECRET_FILE,
    completeMfaChallenge,
    enrollMfaAndFinish,
    installMfaSecretCapture,
    readEnrolledSecret,
    signInWithPassword,
    waitForWorkspaceSettled,
    whichMfaPath,
} from "./helpers/auth-flow";

export const AUTH_FILE = "e2e/.auth/admin.json";
/**
 * Persisted after the first enrollment so later runs can serve the challenge
 * path without the operator knowing the server-generated TOTP secret. The
 * whole directory is gitignored.
 */
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@skyrict.io";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "Admin123!";

/**
 * Persist the authenticated storage state deterministically.
 *
 * The caller MUST call waitForWorkspaceSettled(page) BEFORE this function: the
 * workspace shell rotates the refresh token on mount, and closing the page
 * mid-flight aborts the Set-Cookie response while the backend has already
 * advanced the hash — the next context then presents a stale token, trips the
 * reuse detector, and revokes the session family. Waiting for the sidebar user
 * menu (rendered only after restore() resolved and Set-Cookie was applied)
 * ensures the captured cookie is exactly the token the smoke context will
 * consume first.
 */
async function saveAuthState(page: Page) {
    await page.close();
    const state = await page.context().storageState({ path: AUTH_FILE });
    const hasWorkspaceCookie = state.cookies.some(
        (cookie) =>
            cookie.name === "skyrict_session" &&
            cookie.domain === "default.localhost",
    );
    if (!hasWorkspaceCookie) {
        throw new Error(
            "Workspace session cookie was not persisted to storage state; the smoke suite would start unauthenticated.",
        );
    }
    return state;
}

// The enrollment arm signs in, verifies TOTP, then waits for the handoff to
// navigate off the signin host; on a cold CI stack (the security phase rebuilds
// the cluster and wipes Postgres) that consistently takes ~15-20s and the
// global 30s test timeout is not enough with the handoff poll. The poll is
// 100s (enrollMfaAndFinish) to absorb the first-attempt ~45s stall on the
// freshly started stack (PERF-WEB-002), so the test budget must clear
// signin + enrollment + poll + settled + storage-state write.
setup.setTimeout(180_000);

setup("authenticate as the seeded admin", async ({ page }) => {
    // e2e/.auth is gitignored (holds the TOTP secret + storage state), so it
    // does not exist on a fresh CI checkout - create it before the first write.
    mkdirSync("e2e/.auth", { recursive: true });

    // Capture the MFA setup response before sign-in: the setup-MFA page calls
    // the API on mount, so the enrollment arm needs the listener attached
    // before the handoff happens. Harmless on the challenge path.
    const getMfaSecret = installMfaSecretCapture(page);

    await page.goto("/signin"); // workspace surface 302s to {slug}.signin.{apex}/signin
    await signInWithPassword(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    const path = await whichMfaPath(page);
    if (path === "challenge") {
        const enrolledSecret = readEnrolledSecret();
        expect(
            enrolledSecret,
            "E2E_TOTP_SECRET must be set when the admin already has MFA enrolled.",
        ).toBeTruthy();
        await completeMfaChallenge(page, enrolledSecret);
        // Wait for the workspace shell's session hydration to finish BEFORE
        // closing the page: close() aborts an in-flight /api/auth/session, the
        // backend still completes the rotation, and admin.json then holds a stale
        // token whose first presentation trips the reuse detector (see
        // waitForWorkspaceSettled docstring). The sidebar user menu renders the
        // email only after restore() resolved AND its Set-Cookie reached the jar.
        await waitForWorkspaceSettled(page);
        await saveAuthState(page);
        return;
    }

    // Persist the server-generated secret so a later run can play the challenge
    // path without the operator knowing it. EnrollMfaAndFinish writes it before
    // the TOTP loop so a clock-boundary failure still leaves a recoverable
    // secret.
    await enrollMfaAndFinish(page, {
        secretGetter: getMfaSecret,
        knownSecret: readEnrolledSecret(),
        onWritten: (secret) => writeFileSync(TOTP_SECRET_FILE, secret, "utf8"),
    });
    // Same settled-wait rationale as the challenge arm above.
    await waitForWorkspaceSettled(page);
    await saveAuthState(page);
});
