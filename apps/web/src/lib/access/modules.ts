"use client";

import { useEffect, useState } from "react";

import { getMyRoles } from "@/lib/api/identity-api";

export type ModuleKey = "erp" | "agents" | "intelligence";

export interface ModuleAccess {
    erp: boolean;
    agents: boolean;
    intelligence: boolean;
}

export type AccessStatus = "loading" | "ready" | "error";

export interface ModuleAccessState {
    status: AccessStatus;
    access: ModuleAccess;
    roles: string[];
    permissions: string[];
}

const WILDCARD = "*";
const AGENTS_READ = "agents:read";
const INTELLIGENCE_READ = "intelligence:read";

export const MODULE_ORDER: ModuleKey[] = ["agents", "erp", "intelligence"];

const NO_ACCESS: ModuleAccess = {
    erp: false,
    agents: false,
    intelligence: false,
};

/**
 * Derive module access from a user's effective permission set. The wildcard
 * grants every module; otherwise each module requires its own key/prefix.
 */
export function resolveModuleAccess(permissions: string[]): ModuleAccess {
    const set = new Set(permissions);
    const all = set.has(WILDCARD);
    return {
        erp:
            all ||
            permissions.some((permission) => permission.startsWith("erp.")),
        agents: all || set.has(AGENTS_READ),
        intelligence: all || set.has(INTELLIGENCE_READ),
    };
}

export function accessibleModules(access: ModuleAccess): ModuleKey[] {
    return MODULE_ORDER.filter((key) => access[key]);
}

/** True when the user holds the exact permission or the `*` wildcard. */
export function hasPermission(permissions: string[], key: string): boolean {
    return permissions.includes(WILDCARD) || permissions.includes(key);
}

const INITIAL_STATE: ModuleAccessState = {
    status: "loading",
    access: NO_ACCESS,
    roles: [],
    permissions: [],
};

/**
 * How long a resolved permission set is trusted before it is re-validated.
 *
 * The cache exists because `/roles/me` is read by the shell gate, the route
 * guard, and every permission-aware card on a page - without it a single
 * navigation issued one identical request per consumer. A short TTL keeps a
 * role change (or revocation) picked up within a few minutes while a full page
 * load always starts clean.
 */
const ACCESS_CACHE_TTL_MS = 5 * 60 * 1000;

let inFlight: Promise<ModuleAccessState> | null = null;
let cachedState: ModuleAccessState | null = null;
let cachedAt = 0;

/**
 * Single-flight, short-lived-cached resolver so the shell, route guard, and
 * every permission-aware card share ONE `/roles/me` request instead of issuing
 * one each. Concurrent callers coalesce onto the in-flight promise; callers
 * after it settles are answered from the cache until the TTL lapses.
 *
 * Failures are deliberately NOT cached: a transient network blip must not lock
 * the user out of a module (or bounce them off a page) for the whole TTL - the
 * next mount retries.
 */
function fetchAccessState(): Promise<ModuleAccessState> {
    if (inFlight) return inFlight;
    inFlight = getMyRoles()
        .then((data) => {
            const next: ModuleAccessState = {
                status: "ready",
                access: resolveModuleAccess(data.permissions),
                roles: data.roles,
                permissions: data.permissions,
            };
            cachedState = next;
            cachedAt = Date.now();
            return next;
        })
        .catch(() => {
            return {
                status: "error",
                access: NO_ACCESS,
                roles: [],
                permissions: [],
            } satisfies ModuleAccessState;
        })
        .finally(() => {
            inFlight = null;
        });
    return inFlight;
}

/**
 * The cached permission set, regardless of age. Used to seed the first render
 * of a hook so a navigation never falls back to the loading state while a
 * revalidation is in flight.
 *
 * Returns null while server-rendering on purpose. A Next server process serves
 * every tenant, so a process-wide cache could seed one tenant's permissions
 * into another tenant's HTML. The cache is only ever *populated* by the
 * client-side callers (the hook's effect), but the guard makes that invariant
 * structural instead of accidental.
 */
function peekAccessState(): ModuleAccessState | null {
    if (typeof window === "undefined") return null;
    return cachedState;
}

/**
 * Resolve module access, revalidating at most once per TTL.
 *
 * A stale-but-present cache is returned to the caller immediately and the
 * refresh is kicked off in the background (stale-while-revalidate): the
 * previous answer keeps the chrome stable instead of flashing a skeleton.
 */
export async function getModuleAccess(): Promise<ModuleAccessState> {
    const cached = cachedState;
    if (cached && Date.now() - cachedAt < ACCESS_CACHE_TTL_MS) return cached;
    if (cached) {
        // Stale-while-revalidate: hand back the previous answer and refresh in
        // the background so the caller never falls back to a loading state.
        void fetchAccessState();
        return cached;
    }
    return fetchAccessState();
}

/**
 * Force a revalidation, bypassing the TTL, and resolve with the fresh state.
 *
 * Use after an event that can change the effective permissions (a role edit,
 * a workspace switch) when the caller needs the new answer rather than the
 * cached one. Concurrent callers coalesce onto the same request.
 */
export async function refreshModuleAccess(): Promise<ModuleAccessState> {
    return fetchAccessState();
}

/**
 * Drop the cached permission set. Call on sign-out (or any event that can
 * change the effective roles) so the next read reflects the new identity
 * instead of serving the previous user's access.
 */
export function clearModuleAccess(): void {
    cachedState = null;
    cachedAt = 0;
}

/**
 * Subscribe to module access. The first render is seeded from the cache, and
 * the effect only reaches the network when the cache is stale or empty - so
 * repeat navigations inside a session resolve synchronously.
 */
export function useModuleAccess(): ModuleAccessState {
    const [state, setState] = useState<ModuleAccessState>(
        peekAccessState() ?? INITIAL_STATE,
    );

    useEffect(() => {
        let cancelled = false;
        void getModuleAccess().then((next) => {
            if (!cancelled) setState(next);
        });
        return () => {
            cancelled = true;
        };
    }, []);

    return state;
}
