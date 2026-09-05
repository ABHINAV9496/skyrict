import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  approvePayslipReview,
  downloadPayslipPdf,
  listPayslipReviews,
  rejectPayslipReview,
} from "@/lib/api/payroll-api";

const httpMock = vi.fn<
  (
    path: string,
    options?: RequestInit,
  ) => Promise<{ data?: unknown; ok?: boolean; status?: number; json?: unknown; blob?: unknown }>
>();

vi.mock("@/lib/api/http", () => ({
  ApiError: class ApiError extends Error {
    readonly status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
  apiFetch: async (_path: string, _options?: RequestInit) => {
    const result = await httpMock(_path, _options ?? {});
    return result.data;
  },
  apiFetchRaw: async (_path: string, _options?: RequestInit) => {
    const result = await httpMock(_path, _options ?? {});
    return result;
  },
  apiList: async (_path: string) => {
    const result = await httpMock(_path, {});
    return result.data;
  },
  apiPost: async (_path: string, body: unknown) => {
    const result = await httpMock(_path, {
      method: "POST",
      body: (body ?? null) as BodyInit | null,
    });
    return result.data;
  },
  buildQueryString: (params: Record<string, unknown>) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      search.set(key, String(value));
    }
    const query = search.toString();
    return query ? `?${query}` : "";
  },
}));

const REVIEW_PAYLOAD = {
  id: "r-1",
  run_id: "run-1",
  employee_id: "emp-1",
  employee_number: "EMP-1",
  employee_name: "A B",
  gross: { amount: "3000.00", currency: "USD" },
  deductions: { amount: "300.00", currency: "USD" },
  net: { amount: "2700.00", currency: "USD" },
  status: "draft",
  version: 1,
  rejected_reason: null,
  reviewed_by: null,
  reviewed_at: null,
  rejected_by: null,
  rejected_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

describe("payslip-review client", () => {
  beforeEach(() => {
    httpMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("maps review rows from the queue endpoint", async () => {
    httpMock.mockResolvedValueOnce({ data: [REVIEW_PAYLOAD] });

    const reviews = await listPayslipReviews({ status: "draft", runId: "run-1" });

    expect(httpMock).toHaveBeenCalledWith(
      "/api/v1/payroll/payslips/reviews?status=draft&run_id=run-1",
      {},
    );
    expect(reviews).toHaveLength(1);
    expect(reviews[0]).toMatchObject({
      id: "r-1",
      runId: "run-1",
      status: "draft",
      version: 1,
      net: { amount: "2700.00", currency: "USD" },
    });
  });

  it("approves a review via its id", async () => {
    httpMock.mockResolvedValueOnce({ data: { ...REVIEW_PAYLOAD, status: "approved" } });

    const review = await approvePayslipReview("r-1");

    expect(httpMock).toHaveBeenCalledWith("/api/v1/payroll/payslips/reviews/r-1/approve", {
      method: "POST",
      body: {},
    });
    expect(review.status).toBe("approved");
  });

  it("rejects a review with a reason", async () => {
    httpMock.mockResolvedValueOnce({ data: { ...REVIEW_PAYLOAD, status: "rejected" } });

    const review = await rejectPayslipReview("r-1", "Wrong base pay");

    expect(httpMock).toHaveBeenCalledWith("/api/v1/payroll/payslips/reviews/r-1/reject", {
      method: "POST",
      body: { reason: "Wrong base pay" },
    });
    expect(review.status).toBe("rejected");
  });

  it("stores the reject reason in the body", async () => {
    let capturedBody: unknown = null;
    httpMock.mockImplementation(async (_path, options) => {
      capturedBody = options?.body ?? null;
      return { data: { ...REVIEW_PAYLOAD, status: "rejected" } };
    });

    await rejectPayslipReview("r-1", "Correct the days");

    expect(capturedBody).toEqual({ reason: "Correct the days" });
  });

  it("triggers a file download for the PDF blob", async () => {
    httpMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
      blob: async () => "pdf-bytes",
    });

    const anchorMock = { click: vi.fn(), remove: vi.fn(), href: "", download: "" };
    const fakeBody = { appendChild: vi.fn(), removeChild: vi.fn() };
    const createElement = vi.fn((tag: string) => {
      void tag;
      return anchorMock;
    }) as unknown as typeof document.createElement;
    const fakeDocument = {
      createElement,
      body: fakeBody as unknown as typeof document.body,
    } as unknown as typeof document;
    vi.stubGlobal("document", fakeDocument);
    vi.stubGlobal(
      "URL",
      class {
        static createObjectURL(_blob: unknown) {
          void _blob;
          return "blob:mock";
        }
        static revokeObjectURL(_url: string) {
          void _url;
        }
      },
    );

    await downloadPayslipPdf("r-1");

    expect(httpMock).toHaveBeenCalledWith("/api/v1/payroll/payslips/reviews/r-1/pdf", {});
    expect(anchorMock.download).toBe("payslip-r-1.pdf");
    expect(anchorMock.click).toHaveBeenCalledOnce();
    expect(anchorMock.remove).toHaveBeenCalledOnce();
    expect(fakeBody.appendChild).toHaveBeenCalledWith(anchorMock);
  });

  it("surfaces errors from the PDF endpoint", async () => {
    httpMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: async () => ({ detail: { message: "payslip review r-1 not found" } }),
    });

    await expect(downloadPayslipPdf("r-1")).rejects.toThrow("payslip review r-1 not found");
  });
});