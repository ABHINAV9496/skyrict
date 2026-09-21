/**
 * Tests for the client read cache.
 *
 * The store is what removes the loading shimmer when navigating between routes,
 * so its contract is pinned here:
 *  - a fresh payload is served without a second request;
 *  - concurrent reads of one key coalesce into a single request;
 *  - an explicit `force` (user refresh) always re-reads;
 *  - a failure is recorded but never turned into a cached success;
 *  - invalidation keeps the payload on screen and revalidates on next read;
 *  - clearing drops everything (sign-out / session loss);
 *  - entries are scoped per tenant.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    clearResourceCache,
    getResourceEntry,
    invalidateResources,
    loadResource,
    resourceKey,
} from "@/lib/cache/resource-cache";

/* ---------- fake browser ---------- */

function fakeStorage() {
    const data = new Map<string, string>();
    return {
        getItem: (key: string) => data.get(key) ?? null,
        setItem: (key: string, value: string) => void data.set(key, value),
        removeItem: (key: string) => void data.delete(key),
        key: (index: number) => [...data.keys()][index] ?? null,
        get length() {
            return data.size;
        },
        clear: () => data.clear(),
        /** test-only peek */
        raw: data,
    };
}

let storage: ReturnType<typeof fakeStorage>;
let hostname: string;

beforeEach(() => {
    storage = fakeStorage();
    hostname = "tester.localhost";
    vi.stubGlobal("window", {
        sessionStorage: storage,
        location: { get hostname() { return hostname; } },
    });
    clearResourceCache();
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

/* ---------- resourceKey ---------- */

describe("resourceKey", () => {
    it("is order-independent and drops empty params", () => {
        const a = resourceKey("crm.leads", {
            status: "new",
            offset: 0,
            limit: 50,
        });
        const b = resourceKey("crm.leads", {
            limit: 50,
            offset: 0,
            status: "new",
        });
        expect(a).toBe(b);
        expect(a).toBe("crm.leads?limit=50&offset=0&status=new");
    });

    it("omits undefined, null and empty values", () => {
        expect(
            resourceKey("crm.leads", {
                status: undefined,
                search: null,
                offset: 0,
                limit: "",
            }),
        ).toBe("crm.leads?offset=0");
        expect(resourceKey("crm.leads")).toBe("crm.leads");
    });
});

/* ---------- loadResource ---------- */

describe("loadResource caching", () => {
    it("serves a fresh payload without a second request", async () => {
        const fetcher = vi.fn().mockResolvedValue({ items: [1, 2] });

        const first = await loadResource("crm.leads", fetcher, {
            ttlMs: 30_000,
        });
        const second = await loadResource("crm.leads", fetcher, {
            ttlMs: 30_000,
        });

        expect(fetcher).toHaveBeenCalledTimes(1);
        expect(second).toBe(first);
    });

    it("re-reads once the TTL lapses", async () => {
        vi.useFakeTimers();
        const fetcher = vi.fn().mockResolvedValue({ v: 1 });

        await loadResource("crm.leads", fetcher, { ttlMs: 1_000 });
        vi.advanceTimersByTime(1_500);
        await loadResource("crm.leads", fetcher, { ttlMs: 1_000 });

        expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("always re-reads when forced (user refresh)", async () => {
        const fetcher = vi.fn().mockResolvedValue({ v: 1 });

        await loadResource("crm.leads", fetcher, { ttlMs: 30_000 });
        await loadResource("crm.leads", fetcher, {
            ttlMs: 30_000,
            force: true,
        });

        expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("coalesces concurrent reads of one key", async () => {
        let resolve: (value: { v: number }) => void = () => undefined;
        const fetcher = vi.fn(
            () =>
                new Promise<{ v: number }>((r) => {
                    resolve = r;
                }),
        );

        const a = loadResource("crm.leads", fetcher);
        const b = loadResource("crm.leads", fetcher);
        const c = loadResource("crm.leads", fetcher);
        resolve({ v: 7 });

        await expect(Promise.all([a, b, c])).resolves.toEqual([
            { v: 7 },
            { v: 7 },
            { v: 7 },
        ]);
        expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it("records a failure without caching data, then retries", async () => {
        const fetcher = vi
            .fn()
            .mockRejectedValueOnce(new Error("offline"))
            .mockResolvedValue({ v: 1 });

        await expect(loadResource("crm.leads", fetcher)).rejects.toThrow(
            "offline",
        );
        expect(getResourceEntry<{ v: number }>("crm.leads").error).toBe(
            "offline",
        );
        expect(getResourceEntry<{ v: number }>("crm.leads").data).toBeUndefined();

        // Not locked into the error: the next read retries the network.
        await expect(loadResource("crm.leads", fetcher)).resolves.toEqual({
            v: 1,
        });
        expect(fetcher).toHaveBeenCalledTimes(2);
        expect(getResourceEntry<{ v: number }>("crm.leads").error).toBeNull();
    });

/* ---------- invalidation ---------- */

describe("invalidateResources", () => {
    it("keeps the payload on screen and revalidates on next read", async () => {
        const fetcher = vi
            .fn()
            .mockResolvedValueOnce({ v: 1 })
            .mockResolvedValueOnce({ v: 2 });

        await loadResource("crm.leads", fetcher, { ttlMs: 60_000 });
        invalidateResources("crm.leads");

        // The entry is stale but present: a remount sees data on first read.
        expect(getResourceEntry<{ v: number }>("crm.leads").data).toEqual({
            v: 1,
        });

        await expect(
            loadResource("crm.leads", fetcher, { ttlMs: 60_000 }),
        ).resolves.toEqual({ v: 2 });
        expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("invalidates a whole prefix with one call", async () => {
        const fetcher = vi.fn().mockResolvedValue({ v: 1 });

        await loadResource("crm.leads", fetcher);
        await loadResource("crm.leads?offset=0", fetcher);
        invalidateResources("crm.leads");

        expect(getResourceEntry("crm.leads").updatedAt).toBe(0);
        expect(getResourceEntry("crm.leads?offset=0").updatedAt).toBe(0);
    });
});

/* ---------- tenant scoping ---------- */

describe("tenant scoping", () => {
    it("keeps separate payloads per tenant slug", async () => {
        const fetcher = vi
            .fn()
            .mockResolvedValueOnce({ tenant: "a" })
            .mockResolvedValueOnce({ tenant: "b" });

        hostname = "alpha.localhost";
        await expect(loadResource("crm.leads", fetcher)).resolves.toEqual({
            tenant: "a",
        });

        hostname = "beta.localhost";
        await expect(loadResource("crm.leads", fetcher)).resolves.toEqual({
            tenant: "b",
        });

        // Switching back serves the first tenant's payload without a request.
        hostname = "alpha.localhost";
        await expect(loadResource("crm.leads", fetcher)).resolves.toEqual({
            tenant: "a",
        });
        expect(fetcher).toHaveBeenCalledTimes(2);
    });
});

/* ---------- stale-while-revalidate (cross-page revision pattern) ---------- */

describe("stale-while-revalidate", () => {
    it("serves the stale payload instantly and revalidates in the background", async () => {
        vi.useFakeTimers();
        const fetcher = vi
            .fn()
            .mockResolvedValueOnce({ v: 1 })
            .mockResolvedValueOnce({ v: 2 });

        await loadResource("crm.leads", fetcher, { ttlMs: 1_000 });
        vi.advanceTimersByTime(2_000);

        // The entry is stale but present: a remount sees data on first read.
        expect(getResourceEntry<{ v: number }>("crm.leads").data).toEqual({
            v: 1,
        });

        // Two overlapping reads of a stale key coalesce onto one request...
        const first = loadResource("crm.leads", fetcher, { ttlMs: 1_000 });
        const second = loadResource("crm.leads", fetcher, { ttlMs: 1_000 });
        await expect(Promise.all([first, second])).resolves.toEqual([
            { v: 2 },
            { v: 2 },
        ]);
        expect(fetcher).toHaveBeenCalledTimes(2);

        // ...and the NEXT touch serves the revalidated payload with no fetch.
        await expect(
            loadResource("crm.leads", fetcher, { ttlMs: 1_000 }),
        ).resolves.toEqual({ v: 2 });
        expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("keeps the old data visible when a background refresh fails", async () => {
        vi.useFakeTimers();
        const fetcher = vi
            .fn()
            .mockResolvedValueOnce({ v: 1 })
            .mockRejectedValueOnce(new Error("offline"));

        await loadResource("crm.leads", fetcher, { ttlMs: 1_000 });
        vi.advanceTimersByTime(2_000);

        await expect(
            loadResource("crm.leads", fetcher, { ttlMs: 1_000 }),
        ).rejects.toThrow("offline");
        const entry = getResourceEntry<{ v: number }>("crm.leads");
        expect(entry.data).toEqual({ v: 1 });
        expect(entry.error).toBe("offline");
    });
});
});