/*
 * AI journey: approval interrupt on a high-value journal entry (SKY-107, commit 5).
 *
 * Exercises the SKY-92 approval seam end to end. The E2E workflow opts the
 * seeded tenant into the journal-entry approval engine (both
 * `approval_engine_enabled` and `je_approval_engine` set in
 * `erp_tenant_settings`), so a draft whose total debit is at or above the
 * seeded 10,000 threshold cannot post directly:
 *
 *   1. the UI "Post" action routes the entry into the engine and the entry is
 *      returned still DRAFT (the AI-assisted step is advisory only);
 *   2. the entry lands in the human approval inbox;
 *   3. approving it completes the single-step workflow and posts the entry.
 *
 * Entries below the threshold still auto-approve, which is why the rest of the
 * finance journeys are unaffected by the global flag.
 */

import { expect } from "@playwright/test";

import { test } from "../fixtures/auth";

test.describe("AI approval interrupt", () => {
    test("high-value entry queues for approval, then posts on approval", async ({
        workspace,
    }) => {
        const { page } = workspace;
        const memo = `E2E approval interrupt ${Date.now()}`;

        // ---- Create a draft at/above the 10,000 approval threshold ----------
        await page.goto("/dashboard/erp/finance/journal-entries");
        await page.getByRole("button", { name: "New entry" }).click();
        const dlg = page.getByRole("dialog", { name: "New journal entry" });
        await expect(dlg).toBeVisible();
        await dlg.getByLabel("Memo").fill(memo);

        const row1 = dlg.locator("table tbody tr").first();
        await row1.locator('input[aria-haspopup="listbox"]').fill("1200");
        await row1.locator('input[aria-haspopup="listbox"]').press("Enter");
        await row1.locator('input[type="number"]').first().fill("12000");

        await dlg.getByRole("button", { name: "Add line" }).click();
        const row2 = dlg.locator("table tbody tr").nth(1);
        await row2.locator('input[aria-haspopup="listbox"]').fill("4000");
        await row2.locator('input[aria-haspopup="listbox"]').press("Enter");
        await row2.locator('input[type="number"]').nth(1).fill("12000");

        await expect(dlg.getByText("Balanced")).toBeVisible();
        await dlg.getByRole("button", { name: "Save draft" }).click();
        await expect(page).toHaveURL(/\/erp\/finance\/journal-entries\/[^/]+$/);
        const draftId = page.url().split("/").pop()!;
        await expect(
            page.getByRole("heading", { level: 1 }).filter({ hasText: memo }),
        ).toBeVisible();
        await expect(page.getByText("Draft", { exact: true })).toBeVisible();

        // ---- Posting is interrupted: the entry stays DRAFT ------------------
        await page.getByRole("button", { name: "Post" }).click();
        // The engine took over instead of posting; the Post action is still
        // offered because the entry is still a draft.
        await expect(page.getByRole("button", { name: "Post" })).toBeEnabled({
            timeout: 15_000,
        });
        await expect(page.getByText("Draft", { exact: true })).toBeVisible();

        // ---- It is waiting in the human approval inbox ----------------------
        await page.goto("/dashboard/erp/approvals");
        const rows = page.getByRole("row").filter({ hasText: "Journal Entry" });
        await expect(rows.first()).toBeVisible({ timeout: 15_000 });

        // Only this journey creates journal entries at/above the threshold, so
        // every pending row belongs to it (CI retries can leave a stale one).
        // Approve each until the queue is clear.
        for (let guard = 0; guard < 5; guard += 1) {
            const before = await rows.count();
            if (before === 0) break;
            await rows.first().getByRole("button", { name: "Review" }).click();
            const dialog = page.getByRole("dialog");
            await expect(dialog).toContainText("Journal Entry review");
            await dialog.getByRole("button", { name: "Approve" }).click();
            await expect(dialog).toBeHidden();
            await expect.poll(() => rows.count()).toBeLessThan(before);
        }
        await expect(page.getByText(/workflow completed/)).toBeVisible();

        // ---- The human decision released the posting ------------------------
        await page.goto(`/dashboard/erp/finance/journal-entries/${draftId}`);
        // The header status badge is the ``<span class="...bg-emerald...">Posted``
        // chip; the detail grid's ``<dt>`` label also reads "Posted", so scope the
        // assertion to the badge span to disambiguate.
        await expect(
            page.locator("span").getByText("Posted", { exact: true }),
        ).toBeVisible({ timeout: 15_000 });
    });
});
