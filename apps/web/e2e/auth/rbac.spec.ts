/*
 * RBAC journey (SKY-104 auth platform journeys).
 *
 * Proves the seeded finance_viewer account can reach surfaces its
 * permissions allow (finance journal entries) and is cleanly denied at
 * surfaces it lacks (payroll) — with zero payroll data in the DOM.
 *
 * The finance_viewer user has no MFA on first login so the spec drives
 * the real mandatory-MFA enrollment before navigating to the module
 * surfaces. Every context is worker-scoped (see fixtures/auth.ts header).
 */

import { expect, test } from "@playwright/test";

import {
    enrollMfaAndFinish,
    installMfaSecretCapture,
    signInWithPassword,
    waitForWorkspaceSettled,
} from "../helpers/auth-flow";
import { signinUrl, workspaceUrl } from "../support/urls";

test.setTimeout(120_000);

const SLUG = process.env.E2E_TENANT_SLUG ?? "default";
const FINANCE_EMAIL = process.env.E2E_FINANCE_EMAIL ?? "finance@skyrict.io";
const FINANCE_PASSWORD = process.env.E2E_FINANCE_PASSWORD ?? "Finance123!";

test("finance viewer can reach finance surfaces but is denied payroll access", async ({
    page,
}) => {
    // Sign in as the seeded finance_viewer (no MFA enrolled yet → enrollment flow).
    await page.goto(`${signinUrl(SLUG)}/signin`);

    const getMfaSecret = installMfaSecretCapture(page);
    await signInWithPassword(page, FINANCE_EMAIL, FINANCE_PASSWORD);
    await enrollMfaAndFinish(page, { secretGetter: getMfaSecret });
    await waitForWorkspaceSettled(page, FINANCE_EMAIL);

    /* ── positive: finance journal entries ─────────────────────────── */
    await page.goto(
        `${workspaceUrl(SLUG)}/dashboard/erp/finance/journal-entries`,
    );

    // The real finance surface renders its heading — not a denial notice.
    await expect(
        page.getByRole("heading", { name: "Journal Entries" }),
    ).toBeVisible({ timeout: 15_000 });

    /* ── negative: payroll is denied ───────────────────────────────── */
    await page.goto(`${workspaceUrl(SLUG)}/dashboard/erp/payroll`);

    // ModulePermissionDenied renders "No access to Payroll" for the missing
    // erp.payroll.read permission (module-access-boundary.tsx).
    await expect(
        page.getByRole("heading", { name: "No access to Payroll" }),
    ).toBeVisible({ timeout: 15_000 });

    await expect(
        page.getByText(
            "Your roles don't include permission for this area. Ask a workspace owner to update your role or sign in with an account that has access.",
        ),
    ).toBeVisible();

    // The denial UI is full-height and children are never mounted (the
    // ModuleAccessBoundary wraps {children} conditionally), so payroll
    // data is structurally absent from the DOM.
    const pageText = (await page.locator("body").textContent()) ?? "";
    const lowerText = pageText.toLowerCase();

    // No payroll-specific values, employee names, or salary numbers leak.
    expect(lowerText).not.toContain("salary");
    expect(lowerText).not.toContain("gross pay");
    expect(lowerText).not.toContain("net pay");
    expect(lowerText).not.toContain("payslip");
});
