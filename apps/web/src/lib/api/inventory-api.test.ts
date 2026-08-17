import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listAlerts,
  listMovements,
  listProducts,
  listStockLevels,
  listWarehouses,
} from "@/lib/api/inventory-api";
import type { apiFetchEnvelope } from "@/lib/api/http";

const httpMock = vi.fn<typeof apiFetchEnvelope>();

type Envelope = { data?: unknown; meta?: unknown };

/**
 * Simulate the real http helpers: `apiFetchEnvelope` returns the whole
 * envelope, while `apiFetch`/`apiPost`/... unwrap `payload.data`. This mirrors
 * lib/api/http.ts so a regression back to `apiFetch` for a list endpoint
 * (which hands mapList the bare array) is caught by the tests.
 */
vi.mock("@/lib/api/http", () => ({
  apiFetch: async (_path: string, _options?: RequestInit) => {
    const result = await httpMock(_path, _options);
    return (result as Envelope).data;
  },
  apiFetchEnvelope: (_path: string, _options?: RequestInit) =>
    httpMock(_path, _options),
  apiPost: async (_path: string) => {
    const result = await httpMock(_path, { method: "POST" });
    return (result as Envelope).data;
  },
  apiPatch: async (_path: string) => {
    const result = await httpMock(_path, { method: "PATCH" });
    return (result as Envelope).data;
  },
  apiDelete: async (_path: string) => {
    const result = await httpMock(_path, { method: "DELETE" });
    return (result as Envelope).data;
  },
}));

describe("inventory list endpoints", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("maps the products envelope into products with pagination", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          id: "p-1",
          sku: "SKU-1001",
          name: "Steel bracket",
          category: "Hardware",
          unit: "pcs",
          cost_price: ["2.5000", "USD"],
          sell_price: ["8.9900", "USD"],
          reorder_point: "25.0000",
          is_active: true,
          created_at: "2026-07-01T10:00:00Z",
          updated_at: "2026-07-01T10:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listProducts({ page: 1, pageSize: 20 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/inventory/products?page=1&page_size=20",
      {},
    );
    expect(result.meta).toEqual({
      total: 1,
      page: 1,
      pageSize: 20,
      totalPages: 1,
    });
    expect(result.data).toHaveLength(1);
    expect(result.data[0]).toMatchObject({
      id: "p-1",
      sku: "SKU-1001",
      name: "Steel bracket",
      category: "Hardware",
      unit: "pcs",
      costPrice: ["2.5000", "USD"],
      sellPrice: ["8.9900", "USD"],
      reorderPoint: "25.0000",
      isActive: true,
    });
  });

  it("returns an empty list for an empty envelope", async () => {
    httpMock.mockResolvedValue({
      data: [],
      meta: { total: 0, page: 1, page_size: 20, total_pages: 0 },
    });

    const result = await listProducts();

    expect(result.data).toEqual([]);
    expect(result.meta.totalPages).toBe(0);
  });

  it("maps the warehouses envelope", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          id: "w-1",
          name: "Main DC",
          location: "Riyadh",
          is_active: true,
          created_at: "2026-07-01T10:00:00Z",
          updated_at: "2026-07-01T10:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listWarehouses({ page: 1, pageSize: 20 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/inventory/warehouses?page=1&page_size=20",
      {},
    );
    expect(result.data[0]).toMatchObject({ name: "Main DC" });
  });

  it("maps the stock levels envelope", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          id: "s-1",
          product_id: "p-1",
          warehouse_id: "w-1",
          qty_on_hand: "12.0000",
          qty_reserved: "0.0000",
          updated_at: "2026-07-01T10:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listStockLevels({ page: 1, pageSize: 20 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/inventory/stock?page=1&page_size=20",
      {},
    );
    expect(result.data[0]).toMatchObject({
      productId: "p-1",
      warehouseId: "w-1",
      qtyOnHand: "12.0000",
      qtyReserved: "0.0000",
    });
  });

  it("maps the movements envelope", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          id: "m-1",
          product_id: "p-1",
          warehouse_id: "w-1",
          movement_type: "receipt",
          qty: "5.0000",
          ref_type: "adjustment",
          ref_id: "r-1",
          created_at: "2026-07-01T10:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listMovements({ page: 1, pageSize: 20 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/inventory/stock/movements?page=1&page_size=20",
      {},
    );
    expect(result.data[0]).toMatchObject({
      productId: "p-1",
      movementType: "receipt",
      qty: "5.0000",
    });
  });

  it("maps the alerts envelope", async () => {
    httpMock.mockResolvedValue({
      data: [
        {
          product_id: "p-1",
          warehouse_id: "w-1",
          sku: "SKU-1001",
          name: "Steel bracket",
          qty_on_hand: "4.0000",
          reorder_point: "25.0000",
        },
      ],
      meta: { total: 1, page: 1, page_size: 20, total_pages: 1 },
    });

    const result = await listAlerts({ page: 1, pageSize: 20 });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/inventory/alerts?page=1&page_size=20",
      {},
    );
    expect(result.data[0]).toMatchObject({
      productId: "p-1",
      sku: "SKU-1001",
      qtyOnHand: "4.0000",
    });
  });
});
