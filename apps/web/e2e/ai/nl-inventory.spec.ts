/*
 * AI journey: natural-language inventory (SKY-107, commit 2).
 *
 * Creates a product with a real stock level below its reorder point, then asks
 * the supervisor about it by SKU. The deterministic MockProvider echoes the
 * live product line the nl_query gateway returned, so asserting on the on-hand
 * figure proves the tool data reached the model and the answer - the question
 * itself never mentions that number.
 */

import { expect } from "@playwright/test";

import { test } from "../fixtures/auth";
import {
    adjustStock,
    createProduct,
    createWarehouse,
    uniqueRef,
} from "../helpers/inventory-flow";
import { askAgent, expectAnsweringAgent } from "./helpers/chat";

test.describe("AI natural-language inventory", () => {
    test("answers a SKU question from live stock data", async ({ workspace }) => {
        const { page } = workspace;
        const sku = uniqueRef("AI-SKU");

        const product = await createProduct(page, {
            sku,
            name: "E2E AI Inventory Product",
            reorderPoint: "10",
        });
        const warehouse = await createWarehouse(page, {
            name: `AI-WH-${Date.now().toString(36)}`,
        });
        await adjustStock(page, {
            productId: product.id,
            warehouseId: warehouse.id,
            qty: 2,
            refId: uniqueRef("AI-RCV"),
        });

        const answer = await askAgent(page, `Tell me about SKU ${sku}`);

        await expectAnsweringAgent(page, "Inventory Monitor");
        await expect(answer).toContainText(sku);
        // Tool-grounding: on hand=2 only exists in the gateway's product line.
        await expect(answer).toContainText(/on hand=2(?:\.0+)?\b/);
    });
});
