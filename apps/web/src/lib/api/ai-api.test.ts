import { beforeEach, describe, expect, it, vi } from "vitest";

import { getDigest, refreshDigest } from "@/lib/api/ai-api";
import type { apiFetchEnvelope } from "@/lib/api/http";

const httpMock = vi.fn<typeof apiFetchEnvelope>();

type Envelope = { data?: unknown; meta?: unknown };

/**
 * Simulate the real http helpers: `apiFetchEnvelope` returns the whole
 * envelope, while `apiFetch`/`apiPost`/... unwrap `payload.data`. This mirrors
 * lib/api/http.ts.
 */
vi.mock("@/lib/api/http", () => ({
  apiFetch: async (_path: string, _options?: RequestInit) => {
    const result = await httpMock(_path, _options);
    return (result as Envelope).data;
  },
  apiFetchEnvelope: (_path: string, _options?: RequestInit) => httpMock(_path, _options),
  apiPost: async (_path: string) => {
    const result = await httpMock(_path, { method: "POST" });
    return (result as Envelope).data;
  },
}));

const digest = {
  status: "generated",
  source: "live",
  as_of: "2026-08-27",
  title: "Day in review",
  summary: "A quiet day across finance, sales, inventory, and CRM.",
  points: ["No accounts receivable due within 30 days."],
  caveat: null,
  generated_at: "2026-08-27T08:00:00Z",
  model_used: "gpt-4o",
  signals: null,
};

describe("ai narrator digest endpoints", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  it("fetches the digest from the narrator proxy", async () => {
    httpMock.mockResolvedValue({ data: digest, meta: null });

    const result = await getDigest();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/narrator/digest", {});
    expect(result).toEqual(digest);
  });

  it("passes the as_of query to the digest endpoint", async () => {
    httpMock.mockResolvedValue({ data: digest, meta: null });

    await getDigest("2026-08-26");

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/ai/narrator/digest?as_of=2026-08-26",
      {},
    );
  });

  it("requests a forced refresh through the narrator proxy", async () => {
    httpMock.mockResolvedValue({ data: digest, meta: null });

    const result = await refreshDigest();

    expect(httpMock).toHaveBeenCalledWith("/api/v1/ai/narrator/digest/refresh", {
      method: "POST",
    });
    expect(result).toEqual(digest);
  });

  it("supports an as_of query on refresh", async () => {
    httpMock.mockResolvedValue({ data: digest, meta: null });

    await refreshDigest("2026-08-25");

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/ai/narrator/digest/refresh?as_of=2026-08-25",
      { method: "POST" },
    );
  });
});
