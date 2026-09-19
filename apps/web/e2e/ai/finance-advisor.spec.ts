/*
 * AI journey: finance advisor / AI journal draft (SKY-107, commit 4).
 *
 * Drives the finance "AI Draft" dialog with the deterministic MockProvider.
 * Unlike the defensive dev-owned finance journey, this spec asserts the real
 * AI path succeeded: the mocked provider returns a balanced two-line entry
 * from the live chart of accounts, so the fallback notice must NOT appear and
 * the draft must be applicable and saveable.
 */

import { expect } from "@playwright/test";

import { test } from "../fixtures/auth";

test.describe("AI finance draft", () => {
    test("drafts, applies, and saves a balanced journal entry", async ({
        workspace,
    }) => {
        const { page } = workspace;
        const memo = "E2E AI advisor office supplies 500";

        await page.goto("/dashboard/erp/finance/journal-entries");
        await page.getByRole("button", { name: "AI Draft" }).click();

        const dialog = page.getByRole("dialog", { name: "AI Draft Entry" });
        await expect(dialog).toBeVisible();
        await dialog.getByLabel("Description").fill(memo);
        await dialog.getByRole("button", { name: "Generate" }).click();

        // The mock provider answered, so this is a real AI draft, not the
        // deterministic "suggested accounts" fallback.
        await expect(dialog.getByText(/Balanced/)).toBeVisible({
            timeout: 20_000,
        });
        await expect(
            dialog.getByText(/Dr 500\.00 \/ Cr 500\.00/),
        ).toBeVisible();
        await expect(
            dialog.getByText(/suggested accounts/i),
        ).toHaveCount(0);

        await dialog.getByRole("button", { name: "Apply Draft" }).click();

        const createDialog = page.getByRole("dialog", {
            name: "New journal entry",
        });
        await expect(createDialog).toBeVisible();
        const save = createDialog.getByRole("button", {
            name: "Save draft",
        });
        await expect(save).toBeEnabled();
        await save.click();

        await expect(page).toHaveURL(/\/erp\/finance\/journal-entries\/[^/]+$/);
        await expect(
            page.getByRole("heading", { level: 1 }).filter({ hasText: memo }),
        ).toBeVisible({ timeout: 15_000 });
    });
});
