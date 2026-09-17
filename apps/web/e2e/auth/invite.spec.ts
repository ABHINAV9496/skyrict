/*
 * Invite-accept journey (SKY-104 auth platform journeys).
 *
 * Drives the real invite flow end to end through the browser:
 *   - the owner sends an invitation from the members dashboard (UI-driven,
 *     no API shortcut), capturing the one-time accept link from the DOM;
 *   - a fresh browser context accepts the invite (filling the real
 *     accept-accept form with the real password policy), proving the token
 *     exchange and user provisioning work;
 *   - the owner's context verifies the invitee appears in the real members
 *     table with the correct role, confirming the RBAC grant was applied.
 *
 * Every spec owns its browser contexts independently so the refresh-token
 * rotation chain stays intact (see fixtures/auth.ts header). The owner
 * context handles mandatory-MFA exactly like the signin spec.
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

test.setTimeout(120_000);

const SLUG = process.env.E2E_TENANT_SLUG ?? "default";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@skyrict.io";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "Admin123!";

test("invite link is created, accepted, and the invitee appears in the members table", async ({
    browser,
}) => {
    /* ── owner context ─────────────────────────────────────────────── */
    const ownerContext = await browser.newContext({
        baseURL: workspaceUrl(SLUG),
        viewport: { width: 1280, height: 800 },
    });
    const ownerPage = await ownerContext.newPage();

    // Sign in as the owner through the real signin + mandatory MFA surface.
    const getMfaSecret = installMfaSecretCapture(ownerPage);
    await ownerPage.goto(`${signinUrl(SLUG)}/signin`);
    await signInWithPassword(ownerPage, ADMIN_EMAIL, ADMIN_PASSWORD);
    const mfaPath = await whichMfaPath(ownerPage);
    if (mfaPath === "challenge") {
        const secret = readEnrolledSecret();
        expect(
            secret,
            "E2E_TOTP_SECRET must be set when the admin already has MFA enrolled.",
        ).toBeTruthy();
        await completeMfaChallenge(ownerPage, secret);
    } else {
        await enrollMfaAndFinish(ownerPage, { secretGetter: getMfaSecret });
    }
    await waitForWorkspaceSettled(ownerPage, ADMIN_EMAIL);

    /* ── create invitation ─────────────────────────────────────────── */
    const inviteeEmail = `invitee-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}@example.org`;

    await ownerPage.goto(`${workspaceUrl(SLUG)}/dashboard/invite`);
    await expect(
        ownerPage.getByRole("heading", { name: "Invite team", exact: true }),
    ).toBeVisible();

    await ownerPage.getByLabel("Email address").fill(inviteeEmail);

    // Open the role select and pick the standard member role explicitly (no
    // dependency on role sort order or the default-first-role memo). The
    // combobox renders the display label (SYSTEM_ROLE_LABELS), so the option
    // for standard_user is "Member" — not "Standard User".
    await ownerPage.getByLabel("Role").click();
    await ownerPage.getByRole("option", { name: "Member" }).click();

    await ownerPage.getByRole("button", { name: "Send invite" }).click();

    // The one-time accept link is rendered in a <code> element after creation.
    const inviteLinkCode = ownerPage
        .locator("code")
        .filter({ hasText: /invite\?token=/ });
    await expect(inviteLinkCode).toBeVisible({ timeout: 15_000 });
    const acceptUrl = (await inviteLinkCode.textContent()) ?? "";
    expect(acceptUrl).toContain("invite?token=");

    /* ── invitee context (fresh, unauthenticated) ──────────────────── */
    const inviteeContext = await browser.newContext({
        viewport: { width: 1280, height: 800 },
    });
    const inviteePage = await inviteeContext.newPage();
    try {
        await inviteePage.goto(acceptUrl);

        // The accept form shows the raw role name the invitation carries
        // (verify returns role_name from the invitations table, e.g.
        // "standard_user"); display labels only appear in the dashboard.
        await expect(inviteePage.getByText("standard_user")).toBeVisible({
            timeout: 10_000,
        });

        await inviteePage.getByLabel("Full name").fill("Invitee User");

        const inviteePassword = "Invitee123!Pass";
        await inviteePage.getByLabel("Password", { exact: true }).fill(inviteePassword);
        await inviteePage.getByLabel("Confirm password", { exact: true }).fill(inviteePassword);
        await inviteePage
            .getByRole("button", { name: "Accept invitation" })
            .click();

        // The form redirects to the signin surface on success.
        await inviteePage.waitForURL("**/signin?accepted=1**", {
            timeout: 15_000,
        });
    } finally {
        await inviteeContext.close();
    }

    /* ── verify the invitee is now a member ────────────────────────── */
    await ownerPage.goto(`${workspaceUrl(SLUG)}/dashboard/members`);
    await expect(
        ownerPage.getByRole("heading", { name: "Members", exact: true }),
    ).toBeVisible();

    // The invitee row is visible with the correct email and the assigned role
    // badge. The members dashboard renders rows as a <ul>/<li> list — there
    // is no table/cell role, so assert on the row containing the email and
    // the roleDisplayName ("Member" for standard_user) within it.
    const inviteeRow = ownerPage
        .getByRole("listitem")
        .filter({ hasText: inviteeEmail });
    await expect(inviteeRow).toBeVisible({ timeout: 15_000 });
    await expect(inviteeRow).toContainText("Member");

    await ownerContext.close();
});
