/*
 * Full inventory journey E2E spec.
 *
 * Product create → restock → low-stock alert → anomaly detection →
 * semantic search. Uses the worker-scoped `workspace` fixture from
 * fixtures/auth.ts (real UI sign-in as the seeded admin + MFA), then
 * runs as ONE test with sequential test.step() blocks.
 */

import { expect } from "@playwright/test";

import { test } from "./fixtures/auth";
import {
  adjustStock,
  createProduct,
  createWarehouse,
  getAlerts,
  getStockLevels,
  searchProductsSemantic,
  uniqueRef,
} from "./helpers/inventory-flow";
import { generateSuddenStockDrop, scanAnomalies } from "./helpers/anomaly-flow";

test("inventory journey: create, restock, alert, anomaly, semantic search", async ({
  workspace,
}) => {
  const { page } = workspace;

  // Assigned in step 1, used by all subsequent steps.
  let productId!: string;
  let warehouseId!: string;
  let productSku!: string;

  // ── create product and warehouse ──────────────────────────────────────
  await test.step("create a product and warehouse", async () => {
    const product = await createProduct(page, {
      sku: uniqueRef("INV"),
      name: "E2E Inventory Product",
      reorderPoint: "10",
    });
    expect(product.sku).toBeTruthy();
    expect(product.id).toBeTruthy();

    const warehouse = await createWarehouse(page, {
      name: `INV-WH-${Date.now().toString(36)}`,
    });
    expect(warehouse.id).toBeTruthy();

    productId = product.id;
    warehouseId = warehouse.id;
    productSku = product.sku;
  });

  // ── restock and verify stock level ────────────────────────────────────
  await test.step("restock and verify stock level", async () => {
    await adjustStock(page, {
      productId,
      warehouseId,
      qty: 100,
      refId: uniqueRef("INV-RCV"),
    });

    const levels = await getStockLevels(page, { productId, warehouseId });
    const level = levels.find(
      (l) => l.product_id === productId && l.warehouse_id === warehouseId,
    );
    expect(level).toBeDefined();
    expect(String(level!.qty_on_hand)).toBe("100");
  });

  // ── reduce stock below reorder point and verify alert ──────────────────
  await test.step("reduce stock below reorder point and verify alert", async () => {
    await adjustStock(page, {
      productId,
      warehouseId,
      qty: -95,
      refId: uniqueRef("INV-ISS"),
    });

    const { data: alerts } = await getAlerts(page);
    const skuAlert = alerts.find((a) => a.sku === productSku);
    expect(skuAlert).toBeDefined();

    await page.goto("/dashboard/erp/inventory/alerts");
    await expect(page.getByText(productSku)).toBeVisible({ timeout: 15_000 });
  });

  // ── generate anomaly condition and scan ────────────────────────────────
  await test.step("generate anomaly condition and scan", async () => {
    const condition = await generateSuddenStockDrop(page);
    expect(condition.productId).toBeTruthy();

    const result = await scanAnomalies(page);
    expect(result.detected).toBeGreaterThanOrEqual(1);
  });

  // ── navigate to anomalies page and verify ──────────────────────────────
  await test.step("navigate to anomalies page and verify", async () => {
    await page.goto("/dashboard/erp/inventory/anomalies");
    await expect(
      page.getByRole("heading", { name: "Anomaly Feed", exact: true }),
    ).toBeVisible({ timeout: 15_000 });
  });

  // ── semantic search (provider-keyed) ───────────────────────────────────
  await test.step("semantic search serves hybrid results when provider keyed, else degrades", async () => {
    const semanticEnabled = process.env.E2E_SEMANTIC_SEARCH === "true";
    const result = await searchProductsSemantic(page, {
      query: "inventory product",
    });
    expect(Array.isArray(result.data)).toBe(true);
    expect(result.cached).toBe(false);
    if (semanticEnabled) {
      // Provider is configured: the service runs the hybrid (vector + exact)
      // path rather than falling back to exact-only.
      expect(result.degraded).toBe(false);
    } else {
      // Graceful degradation: embedding provider absent, endpoint still 200
      // with a well-formed envelope.
      expect(result.degraded).toBe(true);
      expect(result.model_used).toBeNull();
    }
  });
});
