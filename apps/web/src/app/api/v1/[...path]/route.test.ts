/**
 * Contract tests for the /api/v1/[...path] BFF catch-all proxy.
 *
 * Covers the behavior that makes the generic proxy safe and correct:
 *  - every known ERP segment (crm, sales, finance, inventory, hr, payroll,
 *    portal, ai, dashboards, reports, documents) forwards to Core while
 *    everything else forwards to Identity;
 *  - a query string on the *first* segment must not leak into the target
 *    selection - /api/v1/documents?page=1&page_size=20 is a Core route, not
 *    an Identity lookup (regression: the segment was derived from the path
 *    including the query, so backends answered RFC 7807 404);
 *  - the query string is preserved when forwarding to the backend;
 *  - binary /download is relayed raw through Core (never JSON-wrapped);
 *  - state-changing methods pass the Origin/Referer CSRF gate.
 */

import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const callBackend = vi.fn();
const callBackendRaw = vi.fn();
const assertSameOrigin = vi.fn();
const resolveTenantSlug = vi.fn();
const sessionAccessToken = vi.fn();
const applySessionCookie = vi.fn();

vi.mock("@/lib/server/auth", () => ({
  callBackend: (path: string, options?: unknown) => callBackend(path, options),
  callBackendRaw: (path: string, options?: unknown) => callBackendRaw(path, options),
  assertSameOrigin: (request: unknown) => assertSameOrigin(request),
  resolveTenantSlug: (host: string | null | undefined) => resolveTenantSlug(host),
  sessionAccessToken: (request: unknown) => sessionAccessToken(request),
  applySessionCookie: (response: unknown, refreshToken: string) =>
    applySessionCookie(response, refreshToken),
}));

import { DELETE, GET, PATCH, POST, PUT } from "./route";

function nextRequest(url: string, init?: RequestInit): NextRequest {
  return new NextRequest(url, init as ConstructorParameters<typeof NextRequest>[1]);
}

const CORE_SEGMENTS = [
  "crm",
  "sales",
  "finance",
  "inventory",
  "hr",
  "payroll",
  "portal",
  "ai",
  "approval",
  "dashboards",
  "reports",
  "documents",
];

describe("BFF catch-all proxy segment", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    resolveTenantSlug.mockReturnValue("tenant-acme");
    assertSameOrigin.mockReturnValue(true);
    // Requests without an Authorization header resolve the access token from
    // the httpOnly session cookie (the BFF cookie bridge); the rotated
    // refresh token is written back onto the response.
    sessionAccessToken.mockResolvedValue({
      token: "abc123",
      refreshToken: "refresh-456",
    });
    applySessionCookie.mockImplementation(() => undefined);
    callBackend.mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [] },
      payload: { data: { items: [] }, message: "ok" },
    });
  });

  it.each(CORE_SEGMENTS)("routes the %s segment to Core (not Identity)", async (segment) => {
    callBackend.mockResolvedValue({
      ok: true,
      status: 200,
      data: { items: [] },
      payload: { data: { items: [] }, message: "ok" },
    });

    const response = await GET(
      nextRequest(`http://tenant.localhost/api/v1/${segment}`, {
        method: "GET",
        headers: { authorization: "Bearer abc123" },
      }),
    );

    expect(callBackend).toHaveBeenCalledWith(
      `/${segment}`,
      expect.objectContaining({ target: "core", token: "abc123" }),
    );
    expect(response.status).toBe(200);
  });

  it("routes a non-ERP segment to Identity", async () => {
    callBackend.mockResolvedValue({
      ok: true,
      status: 200,
      data: { id: "user-1" },
      payload: { data: { id: "user-1" }, message: "ok" },
    });

    const response = await GET(
      nextRequest("http://tenant.localhost/api/v1/me", {
        method: "GET",
        headers: { authorization: "Bearer abc123" },
      }),
    );

    expect(callBackend).toHaveBeenCalledWith(
      "/me",
      expect.objectContaining({ target: "identity", token: "abc123" }),
    );
    expect(response.status).toBe(200);
  });

  it("keeps the query string when forwarding to Core", async () => {
    await GET(
      nextRequest("http://tenant.localhost/api/v1/documents?page=1&page_size=20", {
        method: "GET",
      }),
    );

    expect(callBackend.mock.calls[0][0]).toBe("/documents?page=1&page_size=20");
  });

  it("routes the documents list with a page query to Core, not Identity", async () => {
    const response = await GET(
      nextRequest("http://tenant.localhost/api/v1/documents?page=1&page_size=20", {
        method: "GET",
        headers: { authorization: "Bearer abc123" },
      }),
    );

    expect(callBackend).toHaveBeenCalledWith(
      "/documents?page=1&page_size=20",
      expect.objectContaining({ target: "core", token: "abc123" }),
    );
    expect(response.status).toBe(200);
  });

  it("relays /download responses raw through Core without JSON-wrapping", async () => {
    const fileBody = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // %PDF
    callBackendRaw.mockResolvedValue(
      new Response(fileBody, {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="invoice.pdf"',
        },
      }),
    );

    const response = await GET(
      nextRequest("http://tenant.localhost/api/v1/documents/doc-1/download", {
        method: "GET",
      }),
    );

    expect(callBackendRaw).toHaveBeenCalledWith(
      "/documents/doc-1/download",
      expect.objectContaining({ target: "core" }),
    );
    expect(callBackend).not.toHaveBeenCalled();
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toContain("invoice.pdf");
    await expect(response.arrayBuffer()).resolves.toEqual(fileBody.buffer as ArrayBuffer);
  });

  it("returns 502 when the routed service is unreachable", async () => {
    callBackend.mockResolvedValue({ ok: false, status: 0, data: null, payload: {} });

    const response = await GET(
      nextRequest("http://tenant.localhost/api/v1/documents", { method: "GET" }),
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({
      detail: expect.stringContaining("Core service is unavailable"),
    });
  });

  it("requires same-origin for state-changing methods", async () => {
    assertSameOrigin.mockReturnValue(false);
    const request = nextRequest("http://tenant.localhost/api/v1/documents", {
      method: "POST",
      body: JSON.stringify({ title: "x" }),
    });

    const response = await POST(request);

    expect(response.status).toBe(403);
    expect(callBackend).not.toHaveBeenCalled();
  });

  it("exports every HTTP method bound to the proxy", () => {
    expect(typeof GET).toBe("function");
    expect(typeof POST).toBe("function");
    expect(typeof PUT).toBe("function");
    expect(typeof PATCH).toBe("function");
    expect(typeof DELETE).toBe("function");
  });
});