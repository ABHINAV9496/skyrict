/*
 * In-page BFF helpers for inventory operations.
 *
 * All mutations use page.evaluate (real same-origin fetch with credentials)
 * to satisfy the CSRF gate in /api/v1/[...path]/route.ts.
 */

import { type Page } from "@playwright/test";

interface BffResponse<T = unknown> {
  data?: T;
  meta?: Record<string, number>;
  message?: string;
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

function suffix(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export async function createProduct(
  page: Page,
  opts: { sku: string; name?: string; category?: string; reorderPoint?: string | number },
): Promise<{ id: string; sku: string; name: string }> {
  const body: Record<string, unknown> = {
    sku: opts.sku,
    name: opts.name ?? opts.sku,
    reorder_point: opts.reorderPoint ?? "0",
    cost_price: [12.5, "USD"],
    sell_price: [19.99, "USD"],
  };
  if (opts.category) body.category = opts.category;
  const res = await bff<BffResponse>(page, "/api/v1/inventory/products", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return res.data as { id: string; sku: string; name: string };
}

export async function createWarehouse(
  page: Page,
  opts: { name: string },
): Promise<{ id: string; name: string }> {
  const res = await bff<BffResponse>(page, "/api/v1/inventory/warehouses", {
    method: "POST",
    body: JSON.stringify({ name: opts.name, location: "E2E" }),
  });
  return res.data as { id: string; name: string };
}

export async function adjustStock(
  page: Page,
  opts: {
    productId: string;
    warehouseId: string;
    qty: number;
    refId: string;
    reason?: string;
  },
): Promise<Record<string, unknown>> {
  const res = await bff<BffResponse<Record<string, unknown>>>(
    page,
    "/api/v1/inventory/stock/adjustments",
    {
      method: "POST",
      body: JSON.stringify({
        product_id: opts.productId,
        warehouse_id: opts.warehouseId,
        qty: opts.qty,
        reason: opts.reason ?? "e2e-test",
        ref_id: opts.refId,
      }),
    },
  );
  return (res.data ?? res) as Record<string, unknown>;
}

export async function getStockLevels(
  page: Page,
  opts?: { productId?: string; warehouseId?: string },
): Promise<Record<string, unknown>[]> {
  const params = new URLSearchParams();
  if (opts?.productId) params.set("product_id", opts.productId);
  if (opts?.warehouseId) params.set("warehouse_id", opts.warehouseId);
  const qs = params.toString();
  const res = await bff<BffResponse<Record<string, unknown>[]>>(
    page,
    `/api/v1/inventory/stock${qs ? `?${qs}` : ""}`,
  );
  return res.data ?? [];
}

export async function getAlerts(
  page: Page,
): Promise<{ data: Record<string, unknown>[]; meta: Record<string, number> }> {
  const res = await bff<BffResponse<Record<string, unknown>[]>>(
    page,
    "/api/v1/inventory/alerts",
  );
  return { data: res.data ?? [], meta: res.meta ?? {} };
}

export async function listProducts(
  page: Page,
  params?: { page?: number; pageSize?: number; includeInactive?: boolean },
): Promise<{ data: Record<string, unknown>[]; meta: Record<string, number> }> {
  const qs = new URLSearchParams();
  if (params?.page) qs.set("page", String(params.page));
  if (params?.pageSize) qs.set("page_size", String(params.pageSize));
  if (params?.includeInactive) qs.set("include_inactive", "true");
  const q = qs.toString();
  const res = await bff<BffResponse<Record<string, unknown>[]>>(
    page,
    `/api/v1/inventory/products${q ? `?${q}` : ""}`,
  );
  return { data: res.data ?? [], meta: res.meta ?? {} };
}

export async function searchProductsSemantic(
  page: Page,
  opts: { query: string },
): Promise<{
  data: Record<string, unknown>[];
  cached: boolean;
  degraded: boolean;
  model_used: string | null;
  latency_ms: number | null;
}> {
  const url = `/api/v1/ai/inventory/search?q=${encodeURIComponent(opts.query)}`;
  const res = await bff<Record<string, unknown>>(page, url);
  return {
    data: Array.isArray(res.data) ? (res.data as Record<string, unknown>[]) : [],
    cached: res.cached === true,
    degraded: res.degraded === true,
    model_used: typeof res.model_used === "string" ? res.model_used : null,
    latency_ms: typeof res.latency_ms === "number" ? res.latency_ms : null,
  };
}

export function uniqueRef(prefix: string): string {
  return `${prefix}-${suffix()}`;
}
