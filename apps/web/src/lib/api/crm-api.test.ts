import { beforeEach, describe, expect, it, vi } from "vitest";

import { listLeads, listQuery } from "@/lib/api/crm-api";
import type { apiFetchEnvelope } from "@/lib/api/http";

const apiFetchMock = vi.fn<typeof apiFetchEnvelope>();

vi.mock("@/lib/api/http", () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...(args as Parameters<typeof apiFetchEnvelope>)),
  apiFetchEnvelope: (...args: unknown[]) =>
    apiFetchMock(...(args as Parameters<typeof apiFetchEnvelope>)),
  apiPost: (...args: unknown[]) => apiFetchMock(...(args as Parameters<typeof apiFetchEnvelope>)),
}));

describe("listQuery", () => {
  it("builds an offset/limit query", () => {
    expect(listQuery({ offset: 50, limit: 50 })).toBe("?offset=50&limit=50");
  });

  it("skips nullish and empty values", () => {
    expect(listQuery({ status: undefined, source: null, empty: "", offset: 0 })).toBe(
      "?offset=0",
    );
  });

  it("serializes booleans", () => {
    expect(listQuery({ include_inactive: true })).toBe("?include_inactive=true");
  });

  it("returns an empty string when nothing is provided", () => {
    expect(listQuery({})).toBe("");
  });
});

describe("listLeads", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("maps the wire payload into domain leads with pagination", async () => {
    apiFetchMock.mockResolvedValue({
      data: [
        {
          id: "lead-1",
          status: "contacted",
          first_name: "Ava",
          last_name: "Whitmore",
          company: "Northwind Traders",
          source: "website",
          created_at: "2026-07-01T10:00:00Z",
        },
      ],
      meta: { total: 1, page: 1, page_size: 50, total_pages: 1 },
    });

    const result = await listLeads({ status: "contacted", offset: 0, limit: 50 });

    expect(apiFetchMock).toHaveBeenCalledWith(
      "/api/v1/crm/leads?status=contacted&offset=0&limit=50",
    );
    expect(result.meta.total).toBe(1);
    expect(result.data[0]).toMatchObject({
      id: "lead-1",
      status: "contacted",
      firstName: "Ava",
      lastName: "Whitmore",
      company: "Northwind Traders",
      source: "website",
    });
  });

  it("defaults missing fields defensively", async () => {
    apiFetchMock.mockResolvedValue({
      data: [{ id: "lead-2" }],
      meta: { total: 0, page: 1, page_size: 50, total_pages: 0 },
    });

    const result = await listLeads();

    expect(result.data[0]).toMatchObject({
      id: "lead-2",
      status: "new",
      firstName: null,
      email: null,
    });
    expect(result.meta).toEqual({ total: 0, page: 1, page_size: 50, total_pages: 0 });
  });
});
