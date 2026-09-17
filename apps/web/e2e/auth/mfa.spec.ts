/*
 * Mandatory-MFA lifecycle (SKY-104 auth platform journeys).
 *
 * A tenant owner registered through the real signup wizard must complete MFA
 * enrollment on FIRST sign-in (/setup-mfa), then present a valid TOTP code on
 * EVERY subsequent sign-in before the workspace opens. Proves the full loop:
 * register -> first-login enrollment -> sign out -> challenge -> workspace.
 *
 * The second sign-in asserts the challenge path, NOT enrollment: enrollment is
 * a one-time gate (login-form.tsx pushes /setup-mfa only for the mfa_setup
 * status; an enrolled account gets mfa_challenge instead).
 */

import { expect, test } from "@playwright/test";

import {
    completeMfaChallenge,
    firstOwnerSignInAndEnrollMfa,
    signInWithPassword,
    waitForWorkspaceSettled,
    whichMfaPath,
} from "../helpers/auth-flow";
import { registerTenant } from "../helpers/onboarding";

test.setTimeout(120_000);

const password = "E2e!Passw0rd-Strong-2026";

test("enrolls MFA on first login and challenges on every next login", async ({
    browser,
}) => {
    const context = await browser.newContext({
        viewport: { width: 1280, height: 800 },
    });
    const page = await context.newPage();
    try {
        const segment = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
        const tenant = await registerTenant(page, {
            email: `owner-${segment}@example.org`,
            password,
        });

        // First sign-in: mandatory enrollment. The helper attaches the secret
        // capture before the handoff and completes /setup-mfa end to end.
        const secret = await firstOwnerSignInAndEnrollMfa(
            page,
            tenant.email,
            tenant.password,
        );
        await waitForWorkspaceSettled(page, tenant.email);

        // Sign out through the real sidebar user menu (dialog-confirmed logout).
        await page
            .locator("button[aria-haspopup='menu']")
            .filter({ hasText: tenant.email })
            .first()
            .click();
        await page.getByRole("menuitem", { name: "Sign out" }).click();
        await page
            .getByRole("dialog")
            .getByRole("button", { name: "Sign out" })
            .click();
        await page.waitForURL((url) => url.hostname.includes(".signin."), {
            timeout: 20_000,
        });

        // Second sign-in: TOTP challenge with the secret captured at enrollment.
        await signInWithPassword(page, tenant.email, tenant.password);
        expect(await whichMfaPath(page)).toBe("challenge");
        await completeMfaChallenge(page, secret);
        await waitForWorkspaceSettled(page, tenant.email);
    } finally {
        await context.close();
    }
});
