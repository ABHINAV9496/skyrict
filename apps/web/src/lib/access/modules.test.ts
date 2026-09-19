/**
 * Tests for the module-access resolver and its request cache.
 *
 * The cache is what keeps a page from issuing one identical `/roles/me`
 * request per permission-aware consumer (shell gate + route guard + every
 * card). These tests pin the contract:
 *  - concurrent callers coalesce onto a single request;
 *  - a resolved answer is reused inside the TTL;
 *  - a stale answer is served immediately and revalidated in the background;
 *  - a FAILURE is never cached (a blip must not lock the user out);
 *  - `clearModuleAccess()` (sign-out) forces the next read back to the network.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    accessibleModules,
    clearModuleAccess,
    getModuleAccess,
    hasPermission,
    refreshModuleAccess,
    resolveModuleAccess,
} from "@/lib/access/modules";

const getMyRoles = vi.fn();

vi.mock("@/lib/api/identity-api", () => ({
    getMyRoles: () => getMyRoles(),
}));

const ADMIN = { roles: ["owner"], permissions: ["*"] };
const VIEWER = { roles: ["viewer"], permissions: ["erp.crm.read"] };

/* ---------- permission derivation (pure) ---------- */

describe("resolveModuleAccess", () => {
    it("grants every module to the wildcard", () => {
        expect(resolveModuleAccess(["*"])).toEqual({
            erp: true,
            agents: true,
            intelligence: true,
        });
    });

    it("grants erp on any erp.* permission", () => {
        const access = resolveModuleAccess(["erp.crm.read"]);
        expect(access.erp).toBe(true);
        expect(access.agents).toBe(false);
        expect(access.intelligence).toBe(false);
    });

    it("requires the module-specific key for agents and intelligence", () => {
        expect(resolveModuleAccess(["agents:read"]).agents).toBe(true);
        expect(resolveModuleAccess(["intelligence:read"]).intelligence).toBe(
            true,
        );
        // `erp.`-prefixed keys never leak into the other modules.
        expect(resolveModuleAccess(["erp.agents.read"]).agents).toBe(false);
    });

    it("denies everything to a permission-less user", () => {
        expect(resolveModuleAccess([])).toEqual({
            erp: false,
            agents: false,
            intelligence: false,
        });
    });
});

describe("accessibleModules", () => {
    it("returns the accessible modules in display order", () => {
        expect(accessibleModules(resolveModuleAccess(["*"]))).toEqual([
            "agents",
            "erp",
            "intelligence",
        ]);
        expect(accessibleModules(resolveModuleAccess(["erp.hr.read"]))).toEqual(
            ["erp"],
        );
    });
});

describe("hasPermission", () => {
/* ---------- request cache ---------- */

describe("module access cache", () => {
    beforeEach(() => {
        getMyRoles.mockReset();
        clearModuleAccess();
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
        clearModuleAccess();
    });

    it("coalesces concurrent callers into one request", async () => {
        getMyRoles.mockResolvedValue(ADMIN);

        const [first, second, third] = await Promise.all([
            getModuleAccess(),
            getModuleAccess(),
            getModuleAccess(),
        ]);

        expect(getMyRoles).toHaveBeenCalledTimes(1);
        expect(second).toBe(first);
        expect(third).toBe(first);
        expect(first.permissions).toEqual(["*"]);
    });

    it("reuses the resolved answer inside the TTL", async () => {
        getMyRoles.mockResolvedValue(ADMIN);

        await getModuleAccess();
        await getModuleAccess();
        vi.advanceTimersByTime(60 * 1000);
        await getModuleAccess();

        expect(getMyRoles).toHaveBeenCalledTimes(1);
    });

    it("serves the stale answer immediately and revalidates in the background", async () => {
        getMyRoles.mockResolvedValue(ADMIN);
        await getModuleAccess();
        expect(getMyRoles).toHaveBeenCalledTimes(1);

        // Past the TTL the cached answer is still handed to the caller (the
        // chrome must not fall back to a skeleton) while a refresh runs.
        vi.advanceTimersByTime(6 * 60 * 1000);
        getMyRoles.mockResolvedValue(VIEWER);

        const stale = await getModuleAccess();
        expect(stale.permissions).toEqual(["*"]);

        // The background refresh already coalesced the next request.
        const fresh = await refreshModuleAccess();
        expect(fresh.permissions).toEqual(["erp.crm.read"]);
        expect(getMyRoles).toHaveBeenCalledTimes(2);
    });

    it("never caches a failure so the next mount can retry", async () => {
        getMyRoles.mockRejectedValueOnce(new Error("offline"));

        const failed = await getModuleAccess();
        expect(failed.status).toBe("error");
        expect(failed.permissions).toEqual([]);

        // Immediately retried - not locked out of the module for the TTL.
        getMyRoles.mockResolvedValue(ADMIN);
        const retried = await getModuleAccess();
        expect(retried.status).toBe("ready");
        expect(getMyRoles).toHaveBeenCalledTimes(2);
    });

    it("revalidates on demand via refreshModuleAccess", async () => {
        getMyRoles.mockResolvedValue(ADMIN);
        await getModuleAccess();
        expect(getMyRoles).toHaveBeenCalledTimes(1);

        getMyRoles.mockResolvedValue(VIEWER);
        const refreshed = await refreshModuleAccess();

        expect(refreshed.permissions).toEqual(["erp.crm.read"]);
        expect(getMyRoles).toHaveBeenCalledTimes(2);
        // The refreshed answer is now the cached one.
        expect((await getModuleAccess()).permissions).toEqual(["erp.crm.read"]);
        expect(getMyRoles).toHaveBeenCalledTimes(2);
    });

    it("drops the cache on clearModuleAccess (sign-out)", async () => {
        getMyRoles.mockResolvedValue(ADMIN);
        await getModuleAccess();
        await getModuleAccess();
        expect(getMyRoles).toHaveBeenCalledTimes(1);

        clearModuleAccess();
        getMyRoles.mockResolvedValue(VIEWER);
        const next = await getModuleAccess();

        expect(getMyRoles).toHaveBeenCalledTimes(2);
        expect(next.permissions).toEqual(["erp.crm.read"]);
    });
});
    it("accepts the exact key or the wildcard", () => {
        expect(hasPermission(["erp.crm.read"], "erp.crm.read")).toBe(true);
        expect(hasPermission(["*"], "erp.crm.read")).toBe(true);
    });

    it("rejects an unrelated key", () => {
        expect(hasPermission(["erp.crm.read"], "erp.crm.write")).toBe(false);
    });
});
