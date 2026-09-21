/*
 * PERF-WEB-002 cold-start smoke.
 *
 * A fresh page in the authenticated worker context carries the httpOnly
 * session cookie but starts with an EMPTY in-memory access token - the exact
 * cold-load condition that used to produce 401-then-retry API calls and
 * duplicate /roles + /roles/me GETs. Asserts zero /api 401s and at-most-once
 * fetches on the dashboard root AND the roles page (the roles page's direct
 * getMyRoles() used to race the shell's useModuleAccess()).
 *
 * The `workspace` fixture signs in through the real signin surface and keeps
 * one refresh-token rotation chain per worker; opening a NEW page (not a new
 * context) preserves that chain while wiping the in-memory token - the true
 * cold-hydration path. Never load a shared storage-state into two contexts.
 *
 * Proof vs guard: this spec is a REGRESSION GUARD. The `<= 1` assertions pass
 * whether the transport dedup coalesced two concurrent calls into one or only
 * one call was ever made; the PROOF of coalescing is the vitest suite in
 * src/lib/api/http.test.ts, and the trace JSON below is the manual ground
 * truth for the before/after comparison.
 *
 * Trace: run with PERF_TRACE_DIR=apps/web/scripts/perf/traces to dump the
 * request/status/timing record for the committed before/after .json files.
 */

import fs from "node:fs";
import path from "node:path";
import { expect, type Page } from "@playwright/test";

import { test } from "../fixtures/auth";

interface ApiCall {
  url: string;
  status: number;
  ms: number;
}

async function coldTrace(
  page: Page,
  route: string,
): Promise<{ apiCalls: ApiCall[]; firstApiMs: number | null }> {
  const hydrated = page
    .waitForResponse((response) => response.url().includes("/api/auth/session"), {
      timeout: 15_000,
    })
    .catch(() => null);
  const apiCalls: ApiCall[] = [];
  const startedAt = Date.now();
  const onResponse = (response: { url: () => string; status: () => number }) => {
    const url = response.url();
    if (!url.includes("/api/auth/session") && !url.includes("/api/v1/")) return;
    apiCalls.push({
      url: url.split("?")[0],
      status: response.status(),
      ms: Date.now() - startedAt,
    });
  };
  page.on("response", onResponse);
  try {
    await page.goto(route);
    await hydrated;
    await page.waitForTimeout(1500); // let first-row data calls settle
  } finally {
    page.off("response", onResponse);
  }
  return { apiCalls, firstApiMs: apiCalls[0]?.ms ?? null };
}

function counts(apiCalls: ApiCall[]): { byUrl: Map<string, number>; api401s: ApiCall[] } {
  const byUrl = new Map<string, number>();
  for (const call of apiCalls) byUrl.set(call.url, (byUrl.get(call.url) ?? 0) + 1);
  const api401s = apiCalls.filter((call) => call.url.startsWith("/api/v1") && call.status === 401);
  return { byUrl, api401s };
}

test("cold start: zero 401s; roles + roles/me fetched at most once each", async ({
  workspace,
}) => {
  const { context } = workspace;
  const page = await context.newPage(); // cookie carried, JS memory fresh
  const trace: {
    routes: Record<string, { apiCalls: ApiCall[]; firstApiMs: number | null }>;
  } = { routes: {} };

  for (const route of ["/", "/roles"]) {
    const { apiCalls, firstApiMs } = await coldTrace(page, route);
    const { byUrl, api401s } = counts(apiCalls);
    trace.routes[route] = { firstApiMs, apiCalls };

    expect(api401s, `zero /api/v1 401s on cold start of ${route}`).toEqual([]);
    expect(
      byUrl.get("/api/v1/roles/me") ?? 0,
      `/roles/me fetched at most once on ${route}`,
    ).toBeLessThanOrEqual(1);
    expect(
      byUrl.get("/api/v1/roles") ?? 0,
      `/roles fetched at most once on ${route}`,
    ).toBeLessThanOrEqual(1);
  }

  const traceDir = process.env.PERF_TRACE_DIR;
  if (traceDir) {
    fs.mkdirSync(traceDir, { recursive: true });
    fs.writeFileSync(
      path.join(traceDir, "cold-start.json"),
      JSON.stringify({ capturedAt: new Date().toISOString(), ...trace }, null, 2),
    );
  }
});