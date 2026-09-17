/*
 * Sign-in journey (SKY-104 auth platform journeys).
 *
 * Drives the real signin surface through the BFF:
 *   - valid credentials resolve BOTH mandatory-MFA branches (fresh enrollment
 *     on a first-ever login; TOTP challenge once enrolled) and open the
 *     workspace with the session actually usable at the app level;
 *   - a wrong password is rejected with the exact anti-enumeration copy
 *     (ADR-004), the user stays on the signin surface, and no session cookie
 *     is issued.
 *
 * Every spec owns ONE browser context (see fixtures/auth.ts header): identity
 * rotates the refresh token on each /api/auth/session hydration and treats an
 * already-rotated token as reuse, so a context's cookie jar must advance a
 * single rotation chain.
 */

import { expect, test } from "@playwright/test";

import {
    completeMfaChallenge,
    enrollMfaAndFinish,
    installMfaSecretCapture,
    readEnrolledSecret,
    signInWithPassword,
    waitForWorkspaceSettled,
    whichMfaPath,
} from "../helpers/auth-flow";
import { signinUrl, workspaceUrl } from "../support/urls";

test.setTimeout(90_000);

const SLUG = process.env.E2E_TENANT_SLUG ?? "default";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@skyrict.io";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "Admin123!";

test("valid credentials sign in through MFA and open the workspace", async ({
    browser,
}) => {
    const context = await browser.newContext({
        baseURL: workspaceUrl(SLUG),
        viewport: { width: 1280, height: 800 },
    });
    const page = await context.newPage();
    try {
        // The MFA setup page calls the API on mount, so the secret capture must
        // be attached before the login handoff can navigate there.
        const getMfaSecret = installMfaSecretCapture(page);

        await page.goto(`${signinUrl(SLUG)}/signin`);
        await signInWithPassword(page, ADMIN_EMAIL, ADMIN_PASSWORD);

        const path = await whichMfaPath(page);
        if (path === "challenge") {
            const enrolledSecret = readEnrolledSecret();
            expect(
                enrolledSecret,
                "E2E_TOTP_SECRET must be set when the admin already has MFA enrolled.",
            ).toBeTruthy();
            await completeMfaChallenge(page, enrolledSecret);
        } else {
            await enrollMfaAndFinish(page, { secretGetter: getMfaSecret });
        }

        await waitForWorkspaceSettled(page, ADMIN_EMAIL);

        // The session works at the app level: the members dashboard loads the
        // admin's own row through the real members API. The dashboard renders
        // members as list rows (there is no table/cell role), so assert on the
        // row containing the admin's email.
        await page.goto(`${workspaceUrl(SLUG)}/dashboard/members`);
        await expect(
            page.getByRole("heading", { name: "Members", exact: true }),
        ).toBeVisible();
        await expect(
            page.getByRole("listitem").filter({ hasText: ADMIN_EMAIL }),
        ).toBeVisible({ timeout: 15_000 });
    } finally {
        await context.close();
    }
});

test("wrong password is rejected with the anti-enumeration copy and no session", async ({
    browser,
}) => {
    const context = await browser.newContext({
        baseURL: workspaceUrl(SLUG),
        viewport: { width: 1280, height: 800 },
    });
    const page = await context.newPage();
    try {
        await page.goto(`${signinUrl(SLUG)}/signin`);
        await signInWithPassword(page, ADMIN_EMAIL, "Definitely-Wrong-2026!");

        // ADR-004 anti-enumeration: EVERY failure mode surfaces this same message.
        // Next.js also injects a global role="alert" route announcer on the
        // signin surface, so scope the assertion to the form's error alert.
        const alert = page
            .getByRole("alert")
            .filter({ hasText: "Invalid email or password." });
        await expect(alert).toBeVisible({ timeout: 10_000 });
        await expect(alert).toHaveText("Invalid email or password.");

        // The user stays on the signin surface; nothing redirects to the
        // workspace and identity never issued a session cookie.
        await expect(page).toHaveURL((url) =>
            url.hostname.includes(".signin."),
        );
        const sessionCookies = (await context.cookies()).filter(
            (cookie) => cookie.name === "skyrict_session",
        );
        expect(
            sessionCookies,
            "a failed sign-in must not issue a session cookie",
        ).toHaveLength(0);
    } finally {
        await context.close();
    }
});
