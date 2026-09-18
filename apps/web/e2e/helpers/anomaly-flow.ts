/*
 * In-page BFF helpers for the anomaly detection workflow.
 */

import { type Page } from "@playwright/test";

import { adjustStock, createProduct, createWarehouse, uniqueRef } from "./inventory-flow";

interface BffResponse<T = unknown> {
  data?: T;
  meta?: Record<string, number>;
}

async function bff<T = unknown>(
  page: Page,
  url: string,
  init?: RequestInit,
): Promise<T> {
  return page.evaluate(async ([url, init]) => {
    const res = await fetch(url, {
      credentials: "include",
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers as Record<string, string>),
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`BFF ${url} failed: ${res.status} ${text}`);
    }
    return res.json() as Promise<T>;
  }, [url, init] as const);
}

export async function scanAnomalies(
  page: Page,
): Promise<{ detected: number; duplicates_skipped: number }> {
  // The BFF/core relay passes the ai-agent's scan response through verbatim
  // (no envelope), so the body is FLAT: {detected, duplicates_skipped}.
  // `res.data` is undefined here; treat the flat body as the source and keep
  // the enveloped fallback only as a defensive path. Decode without trusting
  // res.data first (that's what masked a successful server-side scan as 0).
  const res = await bff<BffResponse<{ detected: number; duplicates_skipped: number }>>(
    page,
    "/api/v1/ai/anomalies/scan",
    { method: "POST" },
  );
  const src =
    (typeof res.data === "object" && res.data !== null && "detected" in res.data
      ? res.data
      : (res as { detected?: number; duplicates_skipped?: number })) ?? {};
  return {
    detected: src.detected ?? 0,
    duplicates_skipped: src.duplicates_skipped ?? 0,
  };
}

export async function listAnomalies(
  page: Page,
  params?: { status?: string },
): Promise<{ data: Record<string, unknown>[]; meta: Record<string, number> }> {
  const qs = params?.status ? `?status=${encodeURIComponent(params.status)}` : "";
  const res = await bff<BffResponse<Record<string, unknown>[]>>(
    page,
    `/api/v1/ai/anomalies${qs}`,
  );
  return { data: res.data ?? [], meta: res.meta ?? {} };
}

export async function resolveAnomaly(
  page: Page,
  anomalyId: string,
  note: string,
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse>(
    page,
    `/api/v1/ai/anomalies/${anomalyId}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({ note }),
    },
  );
  return (res.data ?? res) as Record<string, unknown>;
}

export async function dismissAnomaly(
  page: Page,
  anomalyId: string,
  note: string,
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse>(
    page,
    `/api/v1/ai/anomalies/${anomalyId}/dismiss`,
    {
      method: "POST",
      body: JSON.stringify({ note }),
    },
  );
  return (res.data ?? res) as Record<string, unknown>;
}

/**
 * Create a sudden-stock-drop condition: +100 receipt then -90 issue within the
 * 48 h window. The `sudden_stock_drop` rule fires (>90 % drop on a positive
 * starting balance).
 */
export async function generateSuddenStockDrop(
  page: Page,
): Promise<{ productId: string; warehouseId: string }> {
  const product = await createProduct(page, {
    sku: uniqueRef("ANOM-DROP"),
    name: "Anomaly: Sudden Stock Drop",
  });
  const warehouse = await createWarehouse(page, {
    name: `ANOM-DROP-WH-${Date.now().toString(36)}`,
  });
  await adjustStock(page, {
    productId: product.id,
    warehouseId: warehouse.id,
    qty: 100,
    refId: uniqueRef("DROP-RCV"),
  });
  await adjustStock(page, {
    productId: product.id,
    warehouseId: warehouse.id,
    qty: -90,
    refId: uniqueRef("DROP-ISS"),
  });
  return { productId: product.id, warehouseId: warehouse.id };
}

/**
 * Create a duplicate-ref condition: receipt adjustment + transfer sharing the
 * same ref_id. The adjustment creates a movement with type "adjustment"; the
 * transfer creates movements with types "issue" and "receipt" under the same
 * ref_id — the `duplicate_movement_ref` rule fires because the ref_id appears
 * with more than one distinct movement_type at the same warehouse.
 */
export async function generateDuplicateRef(
  page: Page,
): Promise<{ refId: string }> {
  const product = await createProduct(page, {
    sku: uniqueRef("DUP"),
    name: "Anomaly: Duplicate Ref",
  });
  const warehouse = await createWarehouse(page, {
    name: `DUP-WH-${Date.now().toString(36)}`,
  });
  const warehouse2 = await createWarehouse(page, {
    name: `DUP-WH2-${Date.now().toString(36)}`,
  });
  const refId = `DUP-${uniqueRef("ref")}`;
  // First: receipt adjustment — creates movement with type "adjustment"
  await adjustStock(page, {
    productId: product.id,
    warehouseId: warehouse.id,
    qty: 50,
    refId,
  });
  // Second: stock transfer with the same ref_id — creates movements with
  // types "issue" (source warehouse) and "receipt" (dest warehouse).
  // Different ref_types in the idempotency key ("adjustment" vs "transfer")
  // so both succeed; the scan rule then sees ref_id with multiple movement
  // types.
  await page.evaluate(async (args) => {
    const res = await fetch("/api/v1/inventory/stock/transfers", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: args.productId,
        from_warehouse_id: args.fromWarehouseId,
        to_warehouse_id: args.toWarehouseId,
        qty: 5,
        ref_id: args.refId,
      }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`Transfer failed: ${res.status} ${text}`);
    }
  }, {
    productId: product.id,
    fromWarehouseId: warehouse.id,
    toWarehouseId: warehouse2.id,
    refId,
  });
  return { refId };
}
