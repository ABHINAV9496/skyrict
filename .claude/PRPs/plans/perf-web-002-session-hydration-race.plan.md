# Plan: [PERF-WEB-002] Eliminate 401-then-200 API race on session hydration; streamline first-load API calls

## Summary
Cold loads produced `401`-then-retry API calls because `/api/v1/*` requests fired before the in-memory access token was hydrated from the httpOnly session cookie, and identical concurrent GETs (notably `/api/v1/roles` + `/api/v1/roles/me`) duplicated network round trips. This plan (a) confirms the session-ready barrier that already exists in `fetchWithSession`, (b) adds transport-level in-flight GET deduplication to the JSON API client so identical concurrent GETs coalesce onto one request, and (c) adds a committed cold-start trace + Playwright smoke spec that pins "zero 401s" and "roles + roles/me at most once per load".

## User Story
As a user opening the workspace app on a cold load,
I want every API call to wait for the session to hydrate and identical reads to share a single request,
So that the first paint never flashes a permission state or 401, and first-load timing improves.

## Problem → Solution
- **Current state (partially fixed):** `fetchWithSession` (http.ts) already hydrates via single-flight `ensureSession()` before the first data request (commit `28e4cdc6`), and `/roles/me` is single-flighted + TTL-cached at the app layer (`lib/access/modules.ts`, commit `29f4375a`). BUT `app/dashboard/roles/roles.tsx` calls `getMyRoles()` directly (line 81), concurrently with the shell's `useModuleAccess()`, so `/api/v1/roles/me` still fires 2× on the roles page cold load; there is no generic in-flight GET dedup, no committed before/after trace, and no Playwright smoke that asserts zero 401 / at-most-once. The old `web-dev.log` at the repo root documents the pre-fix 401 storm (`GET /api/v1/roles/me 401 …`).
- **Desired state:** any number of consumers requesting the same GET concurrently share exactly one network request; the roles page loads `/api/v1/roles/me` once; a committed Playwright-trace smoke proves zero `/api/v1` 401s on cold start and at-most-once fetches for `/roles` + `/roles/me`.

## Metadata
- **Complexity**: Medium (3-8 files, follows existing single-flight patterns)
- **Source PRD**: Inline feature spec `[PERF-WEB-002]` (no PRD file exists in the repo — grep for `PERF-WEB-002` returns nothing)
- **PRD Phase**: standalone
- **Estimated Files**: 7 (2 UPDATE, 3 CREATE, 1 new dir, 1 workflow line)

---

## UX Design

### Before
```
Cold load of a workspace page
┌────────────────────────────────────────────┐
│ 1. Browser has httpOnly session cookie,     │
│    NO in-memory access token                │
│ 2. Shell mounts        → /api/v1/roles/me   │
│    RolesClient mounts  → /api/v1/roles/me   │  ← duplicate
│                         → /api/v1/roles     │
│                         → /api/v1/permissions│
│    (pre-barrier builds: fires blind → 401   │
│     → retry, visible in dev-server.log)     │
│ 3. Permission flash → cards gate late       │
└────────────────────────────────────────────┘
```

### After
```
Cold load of a workspace page
┌────────────────────────────────────────────┐
│ 1. fetchWithSession awaits single-flight    │
│    /api/auth/session hydration first        │
│ 2. Shell + RolesClient /roles/me requests   │
│    COALESCE → one network request           │
│    /api/v1/roles  → one request             │
│    /api/v1/permissions → one request        │
│ 3. Zero 401s logged; cards gate on the      │
│    first resolution                         │
└────────────────────────────────────────────┘
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| Dashboard root cold load | `/roles/me` 1× (shell only) | 1× (unchanged, verified) | hydration barrier already removed the 401-retry round trip |
| Roles page cold load | `/roles/me` 2× (shell + RolesClient direct call) | `/roles/me` 1×, `/roles` 1× | transport-level GET dedup coalesces them |
| Dev/access logs | 401-then-200 pairs on cold start (pre-fix) | zero `/api/v1` 401s | pinned by smoke spec + committed traces |

Purely internal — no visible layout change; the win is fewer requests, zero 401 noise, and faster permission resolution.

---

## Mandatory Reading

Files that MUST be read before implementing (all paths relative to the monorepo root):

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 (critical) | `apps/web/src/lib/api/http.ts` | 188-271 | `fetchWithSession` — the choke point every authenticated call passes through; hydration barrier + 401 retry logic to build the dedup around |
| P0 (critical) | `apps/web/src/lib/api/http.ts` | 28-71, 88-112 | The single-flight `refreshPromise`/`sessionPromise` pattern to mirror exactly |
| P0 (critical) | `apps/web/src/lib/api/http.ts` | 273-315 | `apiFetch`, `apiFetchBody`, `apiFetchWithMeta`, `apiFetchRaw` — where the dedup wrapper slots in (JSON parse layer, NOT the raw-Response layer) |
| P1 (important) | `apps/web/src/lib/access/modules.ts` | 68-119 | The existing `/roles/me` app-layer single-flight + TTL + identity-guarded `.finally` — the convention the new dedup must match so both layers compose |
| P1 (important) | `apps/web/src/lib/cache/resource-cache.ts` | 56-62, 227-278 | In-flight `Map` + `inFlight.get(scoped) === promise` identity-cleanup pattern |
| P1 (important) | `apps/web/src/lib/api/http.test.ts` | 24-57, 63-139 | The vitest fetch-stub harness and existing hydration tests — new dedup tests go in the same file/structure |
| P1 (important) | `apps/web/src/lib/api/identity-api.ts` | 246-249, 412-423 | `listRoles()` and `getMyRoles()` — the exact endpoints whose duplication the PRD targets; both go through `apiFetch` (GET) so they inherit dedup automatically |
| P2 (reference) | `apps/web/src/app/dashboard/roles/roles.tsx` | 75-113 | The direct `getMyRoles()` call that races the shell's `useModuleAccess()` on the roles page |
| P2 (reference) | `apps/web/e2e/dashboard-smoke.spec.ts` | 45-53 | The `gotoRoute()` settle-on-`/api/auth/session` pattern and per-route heading assertions to reuse in the new smoke spec |
| P2 (reference) | `apps/web/e2e/fixtures/auth.ts` | 52-111 | The worker-scoped `workspace` fixture — the new spec opens a **fresh page in the same context** (fresh JS memory, cookie carried) = true cold-hydration path |
| P2 (reference) | `apps/web/playwright.config.ts` | 87-129 | Project-registration pattern (`crm-finance`/`ai` blocks) for the new `perf` project |

## External Documentation
No external research needed — feature uses established internal patterns (single-flight promises, in-flight `Map` coalescing, worker-scoped E2E fixtures). No new dependencies.

---

## Patterns to Mirror

### SINGLE_FLIGHT_PROMISE
```ts
// SOURCE: apps/web/src/lib/api/http.ts:28-30, 66-70 (see also 78, 107-109)
let refreshPromise: Promise<boolean> | null = null;

function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = fetch("/api/auth/refresh", { method: "POST", cache: "no-store" })
      .then(async (response) => { /* … */ })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}
```

### IN_FLIGHT_MAP_WITH_IDENTITY_CLEANUP
```ts
// SOURCE: apps/web/src/lib/cache/resource-cache.ts:61, 227-228, 273-278
const inFlight = new Map<string, Promise<unknown>>();
const pending = inFlight.get(scoped);
if (pending) return pending as Promise<T>;
// …
const promise = fetcher()
  .then(/* … */)
  .catch(/* … */)
  .finally(() => {
    if (inFlight.get(scoped) === promise) inFlight.delete(scoped);
  });
inFlight.set(scoped, promise);
```

### SINGLE_FLIGHT_WITH_TTL_AND_FAILURE_NON_CACHE
```ts
// SOURCE: apps/web/src/lib/access/modules.ts:79-95, 107-118
let inFlight: Promise<ModuleAccessState> | null = null;
function fetchAccessState(): Promise<ModuleAccessState> {
    if (inFlight) return inFlight;
    inFlight = getMyRoles()
        .then((data) => { /* … caches state … */ })
        .catch(() => { /* failure NOT cached */ })
        .finally(() => { inFlight = null; });
    return inFlight;
}
```

### ENVELOPE_PARSE_LAYER
```ts
// SOURCE: apps/web/src/lib/api/http.ts:114-116, 273-275
async function toResult<T>(response: Response): Promise<T> {
  return readPayload<T>(response).then(({ data }) => data);
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  return toResult<T>(await fetchWithSession(path, options));
}
```

### HYDRATION_BARRIER (already in tree — preserve, do not duplicate)
```ts
// SOURCE: apps/web/src/lib/api/http.ts:205-218
let hydrated: "ok" | "none" | "unknown" | null = null;
if (!getAccessToken()) {
  try {
    const session = await ensureSession();
    hydrated = session ? "ok" : "none";
    if (session) {
      headers.set("Authorization", `Bearer ${session.accessToken}`);
    }
  } catch {
    hydrated = "unknown";
  }
}
```

### ERROR_HANDLING
```ts
// SOURCE: apps/web/src/lib/api/http.ts:12-19
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
// 401 handling lives in fetchWithSession (238-268): refresh single-flight then retry once;
// 403 is never treated as 401. Keep this behavior intact.
```

### TEST_STRUCTURE (vitest fetch-stub harness)
```ts
// SOURCE: apps/web/src/lib/api/http.test.ts:33-57
beforeEach(() => {
    setAccessToken(null);
    requests.length = 0;
    respond = () => json({ data: null });
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const authorization = new Headers(init?.headers).get("Authorization");
        requests.push({ url, method: init?.method ?? "GET", authorization });
        return respond(url, authorization);
    });
});
```

### E2E_FIXTURE_COLD_START (fresh page in an authenticated context)
```ts
// SOURCE: apps/web/e2e/fixtures/auth.ts:60-63 (workspace.context) + dashboard-smoke.spec.ts:45-53 (gotoRoute)
const context = await browser.newContext({ baseURL: workspaceUrl(slug), viewport: { width: 1280, height: 800 } });
// new page in the same context = cookie carried, JS memory fresh → cold hydration path
```

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `apps/web/src/lib/api/http.ts` | UPDATE | Add `dedupeGet` in-flight GET coalescing + wire into `apiFetch`, `apiFetchBody`, `apiFetchWithMeta` |
| `apps/web/src/lib/api/http.test.ts` | UPDATE | Unit tests for dedup: coalescing, distinct-query isolation, POST exclusion, non-persistence, hydration single-flight, rejection non-poisoning |
| `apps/web/e2e/perf/session-cold-start.spec.ts` | CREATE | Playwright smoke: fresh page + session-cookie context → zero `/api/v1` 401s, roles + roles/me at most once; writes committed trace when `PERF_TRACE_DIR` set |
| `apps/web/playwright.config.ts` | UPDATE | Register the `perf` project (mirror `crm-finance` block) so the new spec runs in the suite |
| `apps/web/scripts/perf/traces/cold-start.before.json` | CREATE | Committed pre-change trace (captured by running task-3 tooling with the dedup change stashed) |
| `apps/web/scripts/perf/traces/cold-start.after.json` | CREATE | Committed post-change trace (captured after task 2) |
| `.github/workflows/e2e.yml` | UPDATE (1 line) | Add `--project=perf` to the main e2e run (line 219) so the cold-start smoke gates CI |

## NOT Building
- **No changes to the identity token family / rotation semantics.** `refreshAccessToken`, `ensureSession`, and server-side `rotateRefreshToken` (auth.ts:361+) are untouched; the dedup never bypasses or re-enters them.
- **No retry-on-403 logic.** Only the existing `status === 401` branch in `fetchWithSession` recovers; 403 propagates to the caller.
- **No dedup of raw-Response callers.** `fetchWithSession` (public), `apiFetchRaw` (binary), SSE streaming (`/api/v1/ai/agents/chat/stream`, POST + `signal`), and `layout-api.fetchLayout` (reads `response.json()` off the raw Response) stay undeduped — a raw `Response` body is single-consumption, so dedup lives at the JSON parse layer only.
- **No persistent/`sessionStorage` GET caching at the transport layer.** Dedup is in-flight-only; TTL/freshness stays owned by `resource-cache.ts` and `modules.ts`. A settled request is never reused.
- **No changes to `modules.ts`, `resource-cache.ts`, `middleware.ts`, `/api/auth/session/route.ts`, or the dashboard layout.** They degrade no further.
- **~No `roles.tsx` refactor required~ → DELIVERED.** The transport dedup was expected to make the direct `getMyRoles()` call coalesce with the shell's. Live traces proved the two fire sequentially (`/roles` AFTER: `roles/me` ×2, 315/526 ms), so in-flight dedup structurally cannot merge them. The roles page's `canManage` now reads the shared module-access resolver (`getModuleAccess()` in `modules.ts`), and the product tour routes its role gate through it too — every `/roles/me` consumer on a dashboard page shares ONE request per cold load by construction (single-flight + 5-min TTL), making the spec's at-most-once ceiling deterministic instead of timing-dependent.

---

## Step-by-Step Tasks

### Task 1: Verify the existing session-ready barrier (no code change expected)
- **ACTION**: Confirm the hydration barrier already shipped (`fetchWithSession` lines 205-218 waits on single-flight `ensureSession()`; `SessionProvider.restore` uses the same single-flight; `/api/auth/session` is the only pre-hydration call). Run the existing pinned tests to prove it before touching anything.
- **IMPLEMENT**: None. If `pnpm --filter @skyrict/web exec vitest run src/lib/api/http.test.ts` is green, the barrier is in place. If it is NOT green, stop and report — and decide the failure path NOW, before starting: a broken hydration barrier is a load-bearing regression that affects every authenticated request in the app, i.e. a P0 independent of this perf ticket. Do not let PERF-WEB-002 absorb it. The escalation is: pause this ticket, file a dedicated bug (`BUG-WEB-00X — session hydration barrier regression`), fix the barrier on its own commit, get it green, and only then resume this ticket from Task 1 re-verify. This plan's dedup work builds on a working barrier, so resuming without that green would be building on sand.
- **MIRROR**: HYDRATION_BARRIER, SINGLE_FLIGHT_PROMISE
- **IMPORTS**: n/a
- **GOTCHA**: Do not "improve" the barrier here. `ensureSession()` short-circuits when `getAccessToken()` is set (http.ts:89-91) and never hydrates `/api/auth/session` itself — both deliberate. Any change risks re-introducing second server-side rotations per page load, which the backend's reuse detector treats as a token-family revoke.
- **VALIDATE**: `pnpm --filter @skyrict/web exec vitest run src/lib/api/http.test.ts` — all 4 hydration tests pass.

### Task 2: In-flight GET deduplication in the JSON API client
- **ACTION**: Add a `dedupeGet` wrapper to `apps/web/src/lib/api/http.ts` and route the JSON-envelope GET helpers through it. `fetchWithSession`/`apiFetchRaw` stay raw (see NOT Building).
- **IMPLEMENT**: In `http.ts`, next to `toResult`/`readPayload`:
```ts
/** In-flight GET coalescing for the JSON client (see PERF-WEB-002).
 *  Identical concurrent GETs share ONE network request and the same parsed
 *  result. In-flight only: a settled request is never reused (freshness is
 *  owned by resource-cache/modules TTLs), and failures are not cached so the
 *  next caller retries. Raw-Response consumers (apiFetchRaw, fetchWithSession,
 *  SSE streams) are intentionally excluded: a Response body is
 *  single-consumption and streams may carry their own AbortSignal. */
const inFlightGets = new Map<string, Promise<unknown>>();

function getDedupeKey(path: string, options: RequestInit): string | null {
  const method = (options.method ?? "GET").toUpperCase();
  if (method !== "GET") return null;
  if (options.signal) return null; // abort-capable callers own their request
  return `GET ${path}`;
}

function dedupeGet<T>(path: string, options: RequestInit, run: () => Promise<T>): Promise<T> {
  const key = getDedupeKey(path, options);
  if (!key) return run();
  const pending = inFlightGets.get(key);
  if (pending) return pending as Promise<T>;
  const promise = run().finally(() => {
    if (inFlightGets.get(key) === promise) inFlightGets.delete(key);
  });
  inFlightGets.set(key, promise);
  return promise;
}
```
Wire the three JSON helpers through it (each keeps its own parse function so results are fresh parsed values, never a shared stream):
```ts
export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  return dedupeGet(path, options, () => toResult<T>(fetchWithSession(path, options)));
}

export async function apiFetchWithMeta<T>(path: string, options: RequestInit = {}): Promise<Envelope<T>> {
  return dedupeGet(path, options, () => readPayload<T>(fetchWithSession(path, options)));
}

export async function apiFetchBody<T>(path: string, options: RequestInit = {}): Promise<T> {
  return dedupeGet(path, options, () => readBody<T>(fetchWithSession(path, options)));
}
```
(`apiList` at 375-408 calls `apiFetch<T[]>` with the query serialized by `buildQueryString` — deterministically sorted params — so it inherits dedup with distinct list calls correctly separated by query key.)
- **MIRROR**: IN_FLIGHT_MAP_WITH_IDENTITY_CLEANUP (`inFlight.get(scoped) === promise` identity guard), SINGLE_FLIGHT_WITH_TTL_AND_FAILURE_NON_CACHE (rejections delete the key).
- **IMPORTS**: none new — add the map + helpers in `http.ts` itself.
- **GOTCHA 1 (do NOT dedupe at `fetchWithSession`/raw-Response level):** two callers sharing one raw `Response` would race on `response.json()` — the second read of a consumed body throws `TypeError: Response body is already used`. Dedup must share the *parsed* promise (`Promise<T>`), which is why the wrapper wraps `toResult`/`readPayload`/`readBody` and why `apiFetchRaw` + `layout-api.fetchLayout` are excluded.
- **GOTCHA 2 (identity-guarded cleanup):** the `.finally` must compare `inFlightGets.get(key) === promise` before deleting, exactly like `resource-cache.ts:274`, so a stale rejection can't clear a newer request.
- **GOTCHA 3 (401/refresh compat):** dedup shares the whole `run()` including the hydration wait and the 401→`refreshAccessToken`→retry path inside `fetchWithSession`. Concurrent callers therefore observe the recovery together — preserve the retry branch as-is.
- **GOTCHA 4 (signal guard VERIFIED against the ticket's call sites):** the `options.signal` exclusion was checked against every production call site, not just the test harness. The calls this ticket coalesces — `getMyRoles()`/`listRoles()`/`listPermissions()` (`identity-api.ts:246-249, 412-423`) and `useModuleAccess`→`fetchAccessState` (`modules.ts`) — pass NO signal: `roles.tsx`, `modules.ts`, and `identity-api.ts` contain no `AbortController`/`signal`. The only production sites that thread a `signal` into the dedup-wrapped helpers are live-query lists (`documents-overview.tsx:62`/`documents-list.tsx:122` → `listDocuments` → `apiFetchEnvelope`, `documents-api.ts:264-267`; inventory product/movement/stock/warehouse/alert lists; finance `invoices.tsx`'s `AbortController` guards its `.then()` post-hoc and passes no signal into `apiPost`) — those are per-widget abort-on-filter-change semantics where bypassing dedup is correct. So the guard is live but provably does not suppress the fix's target coalescing. Re-verify this if a future refactor adds a signal to `getMyRoles`.
- **VALIDATE**: `pnpm --filter @skyrict/web exec vitest run src/lib/api/http.test.ts` and `pnpm --filter @skyrict/web exec tsc --noEmit`.

### Task 3: Cold-start trace + Playwright smoke (commit-gate)
- **ACTION**: Create `apps/web/e2e/perf/session-cold-start.spec.ts` asserting the acceptance criteria and emitting a trace JSON; register the `perf` project; capture and commit before/after traces; add the project to CI.
- **IMPLEMENT**:
  - Spec (uses the `workspace` fixture; opens a NEW page in the same context — the true cold-hydration path):

```ts
/* PERF-WEB-002 cold-start smoke.
 * A fresh page in the authenticated worker context carries the httpOnly
 * session cookie but starts with an EMPTY in-memory access token - the exact
 * cold-load condition that used to produce 401-then-retry API calls and
 * duplicate /roles + /roles/me GETs. Asserts zero /api 401s and at-most-once
 * fetches on the dashboard root AND the roles page (the roles page's direct
 * getMyRoles() used to race the shell's useModuleAccess()).
 * Trace: run with PERF_TRACE_DIR=apps/web/scripts/perf/traces to dump the
 * request/status/timing record for the committed before/after .json files. */

import fs from "node:fs";
import path from "node:path";
import { expect, type Page } from "@playwright/test";

import { test } from "../fixtures/auth";

interface ApiCall { url: string; status: number; ms: number; }

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

test("cold start: zero 401s; roles + roles/me fetched at most once each", async ({ workspace }) => {
  const { context } = workspace;
  const page = await context.newPage(); // cookie carried, JS memory fresh
  const trace: { routes: Record<string, { apiCalls: ApiCall[] }> } = { routes: {} };

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
```
  - `apps/web/playwright.config.ts` — register the project after the `ai` block (line ~129):
```ts
{
    name: "perf",
    testMatch: /perf[\\/][^\\/]+\.spec\.ts$/,
    dependencies: ["setup"],
    // Cold-start trace (PERF-WEB-002): worker-scoped `workspace` fixture
    // signs in through the real surface; the spec opens a fresh page so the
    // cookie-rotation chain stays private to the worker (see header).
},
```
  - `.github/workflows/e2e.yml` line 219: append `--project=perf` to the main run: `pnpm --filter @skyrict/web exec playwright test --project=setup --project=reports-smoke --project=crm-finance --project=perf --workers=1`.
- **MIRROR**: E2E_FIXTURE_COLD_START, the `gotoRoute` settle pattern, and the `crm-finance` project block.
- **IMPORTS**: `node:fs`, `node:path`, `@playwright/test`, `../fixtures/auth` (no new deps).
- **GOTCHA 1 (fresh page, not fresh context):** do NOT create a new browser context for the cold trace — an unauthenticated context is bounced to `/signin` by middleware (cookie-presence gate, middleware.ts:156-167) and never exercises the hydration path. The new **page** in the authenticated worker context is the cold-hydration scenario.
- **GOTCHA 2 (rotation chains):** never load a shared storage-state into two contexts; the `perf` project must use the worker-scoped `workspace` fixture like `crm-finance`/`ai` (see playwright.config.ts header, lines 31-41).
- **GOTCHA 3 (assert `≤ 1` is a REGRESSION GUARD, not the proof):** React 19 StrictMode double-mounts effects in dev, so `=== 1` would flake — hence `≤ 1`. Be explicit about what this buys: a `≤ 1` assertion passes identically whether dedup coalesced two concurrent calls into one, or only one call was ever made (e.g. some navigation path where the direct `getMyRoles()` doesn't race the shell's). The e2e therefore cannot *prove* the dedup fired. The PROOF of dedup correctness is the vitest coalescing test — "Concurrent identical GETs coalesce" (2× `apiFetch` via `Promise.all`, asserts exactly 1 recorded request; see Testing Strategy). Treat the e2e as a loose regression guard on the cold-start acceptance criteria, and the committed trace JSON as the manual ground truth for the before/after comparison. Do not cite a green e2e alone as evidence the dedup works.
- **VALIDATE**: `pnpm --filter @skyrict/web exec playwright test --project=perf --workers=1` (local dev stack or CI stack; see next section).

### Task 4: Capture and commit before/after traces
- **ACTION**: Produce `apps/web/scripts/perf/traces/cold-start.before.json` (pre-dedup) and `cold-start.after.json` (post-dedup) with the task-3 tooling, and commit both.
- **IMPLEMENT**:
  - BEFORE: `git stash push apps/web/src/lib/api/http.ts` (keep the spec + project changes), run the perf project with the trace dir, copy `cold-start.json` → `traces/cold-start.before.json`, then `git stash pop`.
  - AFTER: with task 2 in place, run again, copy to `traces/cold-start.after.json`.
  - Runs execute on a booted stack: `E2E_BASE_URL=http://default.localhost:3000 PERF_TRACE_DIR=apps/web/scripts/perf/traces pnpm --filter @skyrict/web exec playwright test --project=perf --workers=1` (CI fully booted via compose; otherwise the Playwright `webServer` autoboots `pnpm run dev` — see playwright.config.ts:59-70).
  - **State hygiene — each capture starts from a FRESH login.** BEFORE and AFTER must be two SEPARATE Playwright invocations, never one run reused across the stash/pop cycle. Each invocation creates a brand-new worker context that signs in through the real signin surface (`workspace` fixture), which starts a fresh token family — so no rotation-chain position, session-cookie freshness, or single-use resource state carries from the BEFORE run into the AFTER run. Additionally, restart the Next dev server between the two captures so the in-process `refreshRotations` FIFO memo (keyed `tenantSlug:refreshToken`, `server/auth.ts`) is cold for both; keep `E2E_TENANT_SLUG`/admin credentials identical. This keeps the "fewer requests in AFTER" comparison honest rather than comparing against a polluted second-run state.
- **MIRROR**: bundle-baseline convention (strict-monotonic, committed artifacts — see `scripts/perf/lighthouse-audit.mjs` lines 3-14 and `perf-baseline.json`).
- **IMPORTS**: none.
- **GOTCHA**: commit the traces explicitly — the root `.gitignore` only ignores `scripts/perf/lighthouse-results/` (line 57), so `scripts/perf/traces/` is tracked by default; do not add it to `.gitignore`.
- **VALIDATE**: both `.json` files exist under `scripts/perf/traces/`, are committed, and the AFTER rollup shows: `roles/me ≤ 1` and `roles ≤ 1` on `/roles`, `api401Count: 0` on both routes, and a lower aggregate `/api` request count than BEFORE.

---

## Testing Strategy

### Unit Tests (apps/web/src/lib/api/http.test.ts, new `describe("in-flight GET deduplication")`)
| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| Concurrent identical GETs coalesce | 2× `apiFetch("/api/v1/roles")` via `Promise.all` | exactly 1 recorded request; both resolve with the same `data` | concurrent access |
| Distinct query strings stay distinct | `apiFetch("/api/v1/roles?limit=10")` + `"?limit=20"` concurrently | 2 recorded requests | key granularity |
| POST is never deduped | 2× `apiPost("/api/v1/roles")` concurrently | 2 recorded requests | mutation safety |
| Settled GET is not reused | sequential `apiFetch("/api/v1/roles")` × 2 | 2 recorded requests | freshness (no transport caching) |
| Hydration fires once under coalescing | 2× `apiFetch("/api/v1/roles/me")` concurrently, token null | 1× `/api/auth/session`, 1× `/api/v1/roles/me` | cold-start single RTT |
| Rejected GET does not poison retries | first `apiFetch` responds 500; repeat after settle | first rejects, second fires a new request | failure non-cache |
| Regression: refresh-then-retry still works | existing test (lines 114-139) untouched | unchanged pass | identity semantics |

### Edge Cases Checklist
- [x] Invalid types / empty input — API layer unchanged; parse functions untouched
- [x] Concurrent access — the core dedup case (unit tests above)
- [x] Network failure — rejection deletes the in-flight key; next caller retries fresh
- [x] Permission denied — 403 never enters the 401 retry branch (existing code, unchanged)
- [x] Response body sharing — impossible by construction (dedup at parsed-`Promise<T>` layer; raw-Response consumers excluded)
- [x] AbortSignal callers — excluded from dedup by `getDedupeKey`
- [x] Query-string collisions — sorted serialization from `buildQueryString` keeps keys deterministic

## Validation Commands

### Static Analysis
```bash
pnpm --filter @skyrict/web exec tsc --noEmit
```
EXPECT: Zero type errors (ci-web.yml:42 gate).

### Unit Tests
```bash
pnpm --filter @skyrict/web exec vitest run src/lib/api/http.test.ts
```
EXPECT: All existing hydration tests + new dedup tests pass.

### Full Web Test Suite
```bash
pnpm --filter @skyrict/web exec vitest run
```
EXPECT: No regressions in the API-client surface (do not run `test:e2e` suite-wide unless the full docker stack is booted).

### Browser Validation (cold-start smoke)
```bash
E2E_BASE_URL=http://default.localhost:3000 pnpm --filter @skyrict/web exec playwright test --project=perf --workers=1
```
EXPECT: Spec passes — zero `/api/v1` 401s and roles/roles-me at most once on `/` and `/roles`. (CI boot: `docker compose` per e2e.yml, or let Playwright autoboot the dev server locally.)

### Build
```bash
pnpm --filter @skyrict/web build
```
EXPECT: Production build succeeds (ci-web.yml build gate).

### Manual Validation
- [ ] Fresh anonymous Chrome (or incognito) → workspace signin → land on `/` → dev console/network shows zero `401` statuses on `/api/v1/*` and zero `401` lines appended to `apps/web/dev-server.log`
- [ ] Navigate to `/roles` → Network tab shows `/api/v1/roles/me` exactly once and `/api/v1/roles` exactly once
- [ ] Reload `/roles` → `/api/auth/session` appears once, then the three data calls once each
- [ ] Killing the network mid-load and retrying shows a fresh request (no stale-dedupe hang)

## Acceptance Criteria
- [ ] Task 1 verification passes (existing hydration tests green)
- [ ] In-flight GET dedup implemented in `http.ts` with identity-guarded cleanup; raw-Response/streaming callers untouched
- [ ] New unit tests cover coalescing, query isolation, POST exclusion, freshness, single-flight hydration, and rejection non-poisoning
- [ ] `e2e/perf/session-cold-start.spec.ts` added and `perf` project registered; CI e2e run includes `--project=perf`
- [ ] `cold-start.before.json` + `cold-start.after.json` committed under `apps/web/scripts/perf/traces/`
- [ ] Zero `401`s for `/api/v1/*` in the cold-start trace; `/roles` + `/roles/me` at most once each per load
- [ ] First-load trace shows no regression and fewer API calls on `/roles` than BEFORE
- [ ] `tsc --noEmit`, web vitest, `pnpm --filter @skyrict/web build` all pass

## Completion Checklist
- [ ] Code follows the discovered single-flight / in-flight-Map conventions (SINGLE_FLIGHT_PROMISE, IN_FLIGHT_MAP_WITH_IDENTITY_CLEANUP)
- [ ] Error handling matches codebase style (`ApiError`, failures never cached)
- [ ] No hardcoded values; no new dependencies
- [ ] Tests follow the `http.test.ts` fetch-stub harness and the `workspace` fixture
- [ ] Token-family / rotation semantics untouched (no changes to refresh or session flows)
- [ ] Documentation: trace artifacts + spec header comments suffice; no README changes required
- [ ] Scope additions reviewed: the `roles.tsx`/product-tour consolidation was originally deferred ("may be a follow-up"); it was delivered after BEFORE/AFTER traces proved the transport dedup could not merge the sequential second consumer (see NOT Building)

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Deduping at `Response` level would break shared body reads | Low (design prevents it) | High | Dedup wraps parsed `Promise<T>` only; `apiFetchRaw`/`fetchWithSession`/SSE excluded; unit test asserts parsed values |
| Identity-guard cleanup bug reuses stale results | Low | Medium | `inFlight.get(key) === promise` guard (mirrors resource-cache.ts:274) + tests |
| Rollout order: trace runs before dedup in place | Medium | Low | Task 4 flow stashes only `http.ts` to capture BEFORE, then re-applies for AFTER; each capture is a separate Playwright invocation with a fresh worker-context sign-in (new token family) plus a dev-server restart between captures, so BEFORE/AFTER compare identical cold states |
| E2E flakes from StrictMode double-mount | Medium | Low | Assert `≤ 1` per route; trace shows true counts |
| Parallel workers racing the session rotation chain in the new project | Low | High | `perf` project uses the worker-scoped `workspace` fixture (never shared storage-state), matching `crm-finance`/`ai` |

## Notes
- **Current-tree reality check:** the 401-then-200 storm described in the PRD's old `web-dev.log` commits predates the already-merged hydration barrier (`fetchWithSession` lines 205-218, commit `28e4cdc6`) and module-access single-flight (`modules.ts`, commit `29f4375a`). This plan therefore focuses the *code change* on the missing generic in-flight GET dedup plus the durable trace/smoke gate, and treats the barrier as verified-preexisting (Task 1). The root `web-dev.log` and `apps/web/dev-server.log` files remain as committed pre-fix trace evidence for the PRD's "traces before/after" requirement, supplemented by the new before/after cold-start artifacts.
- **Why `apiFetch` (not `fetchWithSession`) is the dedup point:** `fetchWithSession` returns a raw single-consumption `Response` (streaming/binary consumers, e.g. `sse-client.ts:201`, `layout-api.ts:39`); sharing it corrupts body reads. The JSON client (`apiFetch`, `apiFetchBody`, `apiFetchWithMeta`, `apiList`) parses into values and is where `roles`/`roles/me` flow, so dedup lives there. The app-layer caches (`modules.ts`, `resource-cache.ts`) keep owning TTL freshness; the transport dedup only suppresses concurrent duplicates.
- **Follow-up (out of scope):** `layout-api.fetchLayout` still issues its own GET per consumer; if the ERP dashboard ever mounts two layout readers, route it through `dedupeGet` (it would need a parse-helper variant for its `response.json()` shape).