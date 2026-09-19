"use client";

/**
 * `useResource` - read a `/api/v1` payload through the client cache.
 *
 * The FIRST render is served from the cache (see `getResourceEntry`), so
 * returning to a recently visited route paints its data immediately instead of
 * the loading shimmer; the payload then revalidates in the background once its
 * TTL lapses. A key that has never been loaded renders the loading state, which
 * is what the route's `loading.tsx` / page skeleton covers.
 *
 * `useSyncExternalStore` is used deliberately: it is the API that lets the
 * server snapshot be "no data" (matching the SSR'd skeleton, so hydration is
 * clean) while the client snapshot is "cached data" (so an SPA navigation
 * renders content on the first pass).
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

import {
    DEFAULT_RESOURCE_TTL_MS,
    getResourceEntry,
    getServerResourceEntry,
    loadResource,
    subscribeResource,
    type ResourceEntry,
} from "@/lib/cache/resource-cache";

export interface UseResourceResult<T> extends ResourceEntry<T> {
    /** Refetch now, keeping the current payload on screen (no skeleton flash). */
    reload: () => Promise<void>;
}

export function useResource<T>(
    key: string | null,
    fetcher: () => Promise<T>,
    options: { ttlMs?: number } = {},
): UseResourceResult<T> {
    // The fetcher is read through a ref so an inline arrow does not restart the
    // load on every render - only `key` (and the TTL) decide when to fetch.
    const fetcherRef = useRef(fetcher);
    fetcherRef.current = fetcher;
    const ttl = options.ttlMs ?? DEFAULT_RESOURCE_TTL_MS;

    const subscribe = useCallback(
        (onChange: () => void) =>
            key === null ? () => undefined : subscribeResource(key, onChange),
        [key],
    );
    const getSnapshot = useCallback(
        () =>
            key === null
                ? getServerResourceEntry<T>()
                : getResourceEntry<T>(key),
        [key],
    );

    const entry = useSyncExternalStore(
        subscribe,
        getSnapshot,
        getServerResourceEntry<T>,
    );

    // Read on mount / when the key changes. `loadResource` is a no-op when the
    // cached payload is still fresh, so a route revisit issues no request.
    useEffect(() => {
        if (key === null) return;
        loadResource(key, () => fetcherRef.current(), {
            ttlMs: ttl,
        }).catch(() => {
            // Recorded on the entry; the caller renders the error state.
        });
    }, [key, ttl]);

    // An external invalidation keeps the payload but marks the entry stale
    // (updatedAt 0). Revalidate so a write on another page is picked up without
    // ever dropping back to a skeleton.
    const needsRevalidation =
        entry.settled && entry.data !== undefined && entry.updatedAt === 0;
    useEffect(() => {
        if (key === null || !needsRevalidation) return;
        loadResource(key, () => fetcherRef.current(), {
            force: true,
            ttlMs: ttl,
        }).catch(() => {
            // Recorded on the entry; the caller renders the error state.
        });
    }, [key, needsRevalidation, ttl]);

    const reload = useCallback(async () => {
        if (key === null) return;
        try {
            await loadResource(key, () => fetcherRef.current(), {
                force: true,
                ttlMs: ttl,
            });
        } catch {
            // Surfaced through the entry's error field.
        }
    }, [key, ttl]);

    return { ...entry, reload };
}