/*
 * AI journey: report builder (SKY-107, commit 3).
 *
 * Creates a product below its reorder point, then asks the NL report builder
 * for the stock-on-hand-vs-reorder template. The deterministic MockProvider
 * returns a whitelisted spec for that seeded template; the real engine
 * validates it, runs it through Core, and the preview must contain the live
 * row for the product we created.
 */

import { expect } from "@playwright/test";

import { test } from "../fixtures/auth";
import {
    adjustStock,
    createProduct,
    createWarehouse,
    uniqueRef,
} from "../helpers/inventory-flow";

test.describe("AI report builder", () => {
    test("builds a stock report from a prompt and previews live rows", async ({
        workspace,
    }) => {
        const { page } = workspace;
        const sku = uniqueRef("AI-RPT");

        const product = await createProduct(page, {
            sku,
            name: "E2E AI Report Product",
            reorderPoint: "10",
        });
        const warehouse = await createWarehouse(page, {
            name: `AI-RPT-WH-${Date.now().toString(36)}`,
        });
        await adjustStock(page, {
            productId: product.id,
            warehouseId: warehouse.id,
            qty: 2,
            refId: uniqueRef("AI-RPT-RCV"),
        });

        await page.goto("/dashboard/erp/reports");
        await page
            .getByLabel("Describe the report you want")
            .fill("Stock on hand versus reorder point by SKU");
        await page.getByRole("button", { name: "Generate" }).click();

        // The engine names the resolved catalog template in its answer.
        await expect(
            page.getByText(/Stock on hand vs reorder point report/),
        ).toBeVisible({ timeout: 20_000 });

        const preview = page.locator("table").first();
        await expect(
            preview.getByRole("columnheader", { name: "sku", exact: true }),
        ).toBeVisible();
        await expect(preview.getByRole("cell", { name: sku })).toBeVisible();
        await expect(
            page.getByRole("button", { name: "Save report" }),
        ).toBeVisible();
    });
});
