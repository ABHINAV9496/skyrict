"use client";

/**
 * Client read cache for list/detail API payloads.
 *
 * WHY: every ERP page loaded its data in a mount effect, so navigating away and
 * back re-fetched from zero and re-showed the loading shimmer - even when the
 * answer had been fetched seconds earlier. This store keeps the last answer per
 * key so a remount paints the previous data immediately while it revalidates
 * (stale-while-revalidate).
 *
 * CONTRACT
 *  - `getResourceEntry` returns a STABLE object reference per key, which is what
 *    lets `useSyncExternalStore` serve it as a first-render snapshot. Do not
 *    derive a new object inside it.
 *  - Concurrent reads of the same key coalesce onto ONE request.
 *  - Failures are cached only as an error marker (never as data), so a retry is
 *    always possible and a transient blip cannot freeze an error screen.
 *  - Entries are scoped to the tenant and dropped on sign-out, so one identity's
 *    payload can never be painted for another.
 *  - Server rendering never reads the store: a Next server process serves every
 *    tenant, so a process-wide cache is not tenant-safe there.
 */

import { getTenantSlug } from "@/lib/auth/session-store";

/** How long a resolved payload is served without revalidating. */
export const DEFAULT_RESOURCE_TTL_MS = 30_000;

/** How old a persisted payload may be and still seed the first paint. */
export const PERSIST_MAX_AGE_MS = 5 * 60 * 1000;

const PERSIST_PREFIX = "skyrict:resource:";

/** Bound on in-memory entries so a long session cannot grow without limit. */
const MEMORY_MAX_ENTRIES = 200;

export interface ResourceEntry<T> {
    /** Last successfully loaded payload, if any. */
    data: T | undefined;
    /** Message from the most recent failed load (data, when present, is kept). */
    error: string | null;
    /** When `data` was last refreshed. 0 means "externally invalidated". */
    updatedAt: number;
    /** A request is currently in flight for this key. */
    isLoading: boolean;
    /** A load has settled at least once (used to gate revalidation). */
    settled: boolean;
}

/** Stable identity returned for keys that have never been loaded. */
const EMPTY_ENTRY: ResourceEntry<never> = Object.freeze({
    data: undefined,
    error: null,
    updatedAt: 0,
    isLoading: false,
    settled: false,
});

const entries = new Map<string, ResourceEntry<unknown>>();
const inFlight = new Map<string, Promise<unknown>>();
const listeners = new Map<string, Set<() => void>>();

function isBrowser(): boolean {
    return typeof window !== "undefined";
}

/**
 * Tenant-scoped cache key. The workspace origin is already per-tenant, but the
 * slug is folded in as well so a dev host serving several tenants from one
 * origin (plain localhost:3000) cannot cross-contaminate.
 */
function scopedKey(key: string): string {
    return `${getTenantSlug()}::${key}`;
}

function storageKey(key: string): string {
    return `${PERSIST_PREFIX}${key}`;
}

/** Notify every subscriber of a key (and of the tenant-wide prefix). */
function notify(key: string): void {
    const set = listeners.get(key);
    if (!set) return;
    for (const listener of set) listener();
}

function setEntry<T>(key: string, next: ResourceEntry<T>): void {
    entries.set(key, next);
    evictOldest();
    notify(key);
}

function evictOldest(): void {
    if (entries.size <= MEMORY_MAX_ENTRIES) return;
    const oldest = entries.keys().next().value;
    if (oldest !== undefined) {
        entries.delete(oldest);
        listeners.delete(oldest);
    }
}

function persist(key: string, entry: ResourceEntry<unknown>): void {
    if (!isBrowser() || entry.data === undefined) return;
    try {
        window.sessionStorage.setItem(
            storageKey(key),
            JSON.stringify({ data: entry.data, updatedAt: entry.updatedAt }),
        );
    } catch {
        // Quota or a disabled storage partition: the memory cache still works.
    }
}

/**
 * Seed an entry from sessionStorage the first time a key is read in a browser.
 *
 * A persisted payload is treated as STALE (updatedAt 0) so it paints instantly
 * and then revalidates in the background - never served as if it were fresh.
 * Entries older than PERSIST_MAX_AGE_MS are ignored outright.
 */
function hydrate(key: string): void {
    if (!isBrowser() || entries.has(key)) return;
    let raw: string | null = null;
    try {
        raw = window.sessionStorage.getItem(storageKey(key));
    } catch {
        return;
    }
    if (!raw) return;
    try {
        const parsed = JSON.parse(raw) as { data?: unknown; updatedAt?: number };
        if (parsed.data === undefined) return;
        const age = Date.now() - (parsed.updatedAt ?? 0);
        if (age < 0 || age > PERSIST_MAX_AGE_MS) {
            window.sessionStorage.removeItem(storageKey(key));
            return;
        }
        entries.set(key, {
            data: parsed.data,
            error: null,
            updatedAt: 0,
            isLoading: false,
            settled: true,
        });
    } catch {
        window.sessionStorage.removeItem(storageKey(key));
    }
}

/* ---------------------------------------------------------------------------
 * Public API
 * ------------------------------------------------------------------------- */

/**
 * Deterministic cache key for a read: `name` plus sorted, non-empty params.
 * Sorting means two consumers asking for the same list share one entry
 * regardless of the order they build the params in.
 */
export function resourceKey(
    name: string,
    params: Record<string, string | number | boolean | null | undefined> = {},
): string {
    const parts = Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== null && value !== "")
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([param, value]) => `${param}=${String(value)}`);
    return parts.length > 0 ? `${name}?${parts.join("&")}` : name;
}

/** The current entry for a key, with a stable reference for React snapshots. */
export function getResourceEntry<T>(key: string): ResourceEntry<T> {
    if (!isBrowser()) return EMPTY_ENTRY as ResourceEntry<T>;
    const scoped = scopedKey(key);
    hydrate(scoped);
    return (
        (entries.get(scoped) as ResourceEntry<T> | undefined) ??
        (EMPTY_ENTRY as ResourceEntry<T>)
    );
}

/** Server snapshot: the store is never read while rendering on the server. */
export function getServerResourceEntry<T>(): ResourceEntry<T> {
    return EMPTY_ENTRY as ResourceEntry<T>;
}

/** Subscribe to a key. Returns the unsubscribe function. */
export function subscribeResource(key: string, listener: () => void): () => void {
    if (!isBrowser()) return () => undefined;
    const scoped = scopedKey(key);
    let set = listeners.get(scoped);
    if (!set) {
        set = new Set();
        listeners.set(scoped, set);
    }
    set.add(listener);
    return () => {
        const current = listeners.get(scoped);
        if (!current) return;
        current.delete(listener);
        if (current.size === 0) listeners.delete(scoped);
    };
}

export interface LoadResourceOptions {
    /** Freshness window; within it a cached payload is served without a request. */
    ttlMs?: number;
    /** Bypass the freshness window (explicit user refresh). */
    force?: boolean;
}

/**
 * Read a resource, hitting the network only when the cached payload is missing,
 * older than the TTL, or `force` is set. Concurrent calls for one key coalesce.
 */
export function loadResource<T>(
    key: string,
    fetcher: () => Promise<T>,
    options: LoadResourceOptions = {},
): Promise<T> {
    // Server rendering and prerendering never populate the store.
    if (!isBrowser()) return fetcher();

    const ttl = options.ttlMs ?? DEFAULT_RESOURCE_TTL_MS;
    const scoped = scopedKey(key);

    const pending = inFlight.get(scoped);
    if (pending) return pending as Promise<T>;

    hydrate(scoped);
    const current = entries.get(scoped) as ResourceEntry<T> | undefined;
    const age = current ? Date.now() - current.updatedAt : Number.POSITIVE_INFINITY;
    if (!options.force && current?.data !== undefined && age < ttl) {
        return Promise.resolve(current.data);
    }

    setEntry(scoped, {
        data: current?.data,
        error: null,
        updatedAt: current?.updatedAt ?? 0,
        isLoading: true,
        settled: current?.settled ?? false,
    });

    const promise = fetcher()
        .then((data) => {
            const next: ResourceEntry<T> = {
                data,
                error: null,
                updatedAt: Date.now(),
                isLoading: false,
                settled: true,
            };
            setEntry(scoped, next);
            persist(scoped, next);
            return data;
        })
        .catch((error: unknown) => {
            // Keep whatever payload we already had - a failed background
            // refresh must not blank a screen that has data.
            setEntry(scoped, {
                data: current?.data,
                error:
                    error instanceof Error
                        ? error.message
                        : "Request failed. Please try again.",
                updatedAt: current?.updatedAt ?? 0,
                isLoading: false,
                settled: true,
            });
            throw error;
        })
        .finally(() => {
            if (inFlight.get(scoped) === promise) inFlight.delete(scoped);
        });

    inFlight.set(scoped, promise);
    return promise;
}

/**
 * Mark every entry under a key/prefix stale and notify subscribers.
 *
 * The payload is deliberately KEPT so a mounted consumer refreshes without a
 * skeleton flash; the entry simply revalidates on the next opportunity. Call
 * this after a mutation so lists never keep serving pre-write data.
 */
export function invalidateResources(prefix: string): void {
    if (!isBrowser()) return;
    const scopedPrefix = scopedKey(prefix);
    for (const [scoped, entry] of [...entries]) {
        if (!scoped.startsWith(scopedPrefix)) continue;
        setEntry(scoped, { ...entry, updatedAt: 0 });
        try {
            window.sessionStorage.removeItem(storageKey(scoped));
        } catch {
            // Storage unavailable: memory invalidation already happened.
        }
    }
}

/** Invalidate a single resource key. */
export function invalidateResource(key: string): void {
    invalidateResources(key);
}

/**
 * Drop every cached payload (sign-out, workspace switch). Subscribers fall back
 * to their loading state, which is correct: the next identity must not inherit
 * the previous one's data.
 */
export function clearResourceCache(): void {
    if (!isBrowser()) return;
    const keys = [...entries.keys()];
    entries.clear();
    inFlight.clear();
    for (const scoped of keys) {
        try {
            window.sessionStorage.removeItem(storageKey(scoped));
        } catch {
            // Ignore: nothing else to clean.
        }
        notify(scoped);
    }
}