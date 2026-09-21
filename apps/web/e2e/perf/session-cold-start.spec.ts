/*
 * PERF-WEB-002 cold-start smoke.
 *
 * A fresh page in the authenticated worker context carries the httpOnly
 * session cookie but starts with an EMPTY in-memory access token - the exact
 * cold-load condition that used to produce 401-then-retry API calls and
 * duplicate /roles + /roles/me GETs. Asserts zero /api/v1 401s and bounded
 * fetches on the dashboard root AND the roles page.
 *
 * The `workspace` fixture signs in through the real signin surface and keeps
 * one refresh-token rotation chain per worker; opening a NEW page (not a new
 * context) preserves that chain while wiping the in-memory token - the true
 * cold-hydration path. Never load a shared storage-state into two contexts.
 *
 * Proof vs guard: this spec is a REGRESSION GUARD. The zero-401 assertion is
 * the P0 requirement (a stale-token retry storm would surface here as 401s or
 * as role fetches above the bounded ceilings); the PROOF of coalescing is the
 * vitest suite in src/lib/api/http.test.ts, and the trace JSON below is the
 * manual ground truth for the before/after comparison.
 *
 * Why the roles/me ceilings differ per route: on `/` only the shell's
 * useModuleAccess() (src/lib/access/modules.ts) calls getMyRoles(), so one
 * request is expected. On `/roles` the roles page's own load() (its
 * Promise.all of listRoles + listPermissions + getMyRoles in roles.tsx) is a
 * second, independent consumer; on this stack the two fire sequentially and
 * the in-flight dedup (correctly) does not merge them, so two requests are
 * expected. Any count above the ceiling means retries or a lost dedup.
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
      url: new URL(url).pathname,
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

test("cold start: zero 401s; roles + roles/me fetched within per-route ceilings", async ({
  workspace,
}) => {
  const { context } = workspace;
  const page = await context.newPage(); // cookie carried, JS memory fresh
  const trace: {
    routes: Record<string, { apiCalls: ApiCall[]; firstApiMs: number | null }>;
  } = { routes: {} };

  // Collect first, dump the trace IMMEDIATELY, assert after. The trace JSON is
  // ground truth for the before/after comparison and must exist even when this
  // guard fails on a pre-fix build (a failing run still proves the gap).
  for (const route of ["/", "/roles"]) {
    const { apiCalls, firstApiMs } = await coldTrace(page, route);
    trace.routes[route] = { firstApiMs, apiCalls };
  }

  const traceDir = process.env.PERF_TRACE_DIR;
  if (traceDir) {
    fs.mkdirSync(traceDir, { recursive: true });
    fs.writeFileSync(
      path.join(traceDir, "cold-start.json"),
      JSON.stringify({ capturedAt: new Date().toISOString(), ...trace }, null, 2),
    );
  }

  for (const route of ["/", "/roles"] as const) {
    const { apiCalls } = trace.routes[route];
    const { byUrl, api401s } = counts(apiCalls);

    expect(api401s, `zero /api/v1 401s on cold start of ${route}`).toEqual([]);
    // Roles has exactly ONE consumer (the roles page's listRoles()); more
    // than one request on any route means a retry or a lost dedup.
    const rolesCeiling = 1;
    expect(
      byUrl.get("/api/v1/roles") ?? 0,
      `roles fetched at most ${rolesCeiling} time(s) on ${route}`,
    ).toBeLessThanOrEqual(rolesCeiling);
    // roles/me consumers: shell useModuleAccess everywhere; the roles page's
    // own load() adds a second only on /roles (see route comments above).
    const rolesMeCeiling = route === "/roles" ? 2 : 1;
    expect(
      byUrl.get("/api/v1/roles/me") ?? 0,
      `roles/me fetched at most ${rolesMeCeiling} time(s) on ${route}`,
    ).toBeLessThanOrEqual(rolesMeCeiling);
  }
});
