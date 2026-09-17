/*
 * Signup-wizard CAPTCHA gate (SKY-104 auth platform journeys).
 *
 * The security step of the real signup wizard must reject a wrong text-CAPTCHA
 * answer - staying on the step with the rejection copy AND rotating to a fresh
 * challenge - then accept the correct answer and complete tenant provisioning.
 * The owner account created with the accepted answer must be sign-in ready.
 *
 * The CAPTCHA answer is only exposed in plaintext under ENVIRONMENT=test (the
 * E2E stack's identity setting), so the harness drives the same challenge a
 * human sees without touching any test-only endpoint.
 */

import { expect, test } from "@playwright/test";

import {
    firstOwnerSignInAndEnrollMfa,
    waitForWorkspaceSettled,
} from "../helpers/auth-flow";
import { registerTenant } from "../helpers/onboarding";

test.setTimeout(120_000);

const password = "E2e!Passw0rd-Strong-2026";

test("captcha rejects a wrong answer, rotates, and accepts the correct one", async ({
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
            rejectWrongCaptcha: true,
        });

        // Provisioning handed off to the new tenant's own signin surface - the
        // wizard only completes after the correct answer is accepted.
        await expect(page).toHaveURL(
            new RegExp(
                `${tenant.slug.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\.signin\\.`,
            ),
        );

        // The account (with the password chosen on the rejected step) is real:
        // first sign-in takes the mandatory enrollment path into the workspace.
        await firstOwnerSignInAndEnrollMfa(page, tenant.email, tenant.password);
        await waitForWorkspaceSettled(page, tenant.email);
    } finally {
        await context.close();
    }
});
