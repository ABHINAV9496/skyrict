/**
 * Tests for the session-hydration contract of the authenticated fetch wrapper.
 *
 * On a fresh page load the access token lives only in the httpOnly session
 * cookie, so firing the first API call blind guaranteed a 401 plus a full
 * retry - one wasted round trip per page load. These tests pin the
 * replacement behaviour: hydrate first, exactly one `/api/auth/session` per
 * page load, and never a blind retry.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, apiPost } from "@/lib/api/http";
import { getAccessToken, setAccessToken } from "@/lib/auth/session-store";

interface RecordedRequest {
    url: string;
    method: string;
    authorization: string | null;
}

const requests: RecordedRequest[] = [];

function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

let respond: (url: string, authorization: string | null) => Response;

beforeEach(() => {
    setAccessToken(null);
    requests.length = 0;
    respond = () => json({ data: null });
    vi.stubGlobal(
        "fetch",
        async (input: RequestInfo | URL, init?: RequestInit) => {
            const url = String(input);
            const authorization = new Headers(init?.headers).get(
                "Authorization",
            );
            requests.push({
                url,
                method: init?.method ?? "GET",
                authorization,
            });
            return respond(url, authorization);
        },
    );
});

afterEach(() => {
    vi.unstubAllGlobals();
    setAccessToken(null);
});

function sessionCalls(): RecordedRequest[] {
    return requests.filter((request) => request.url === "/api/auth/session");
}

describe("fetchWithSession hydration", () => {
    it("hydrates the session before the first request instead of eating a 401", async () => {
        respond = (url) =>
            url === "/api/auth/session"
                ? json({
                      authenticated: true,
                      accessToken: "tok-1",
                      user: { id: "u1" },
                  })
                : json({ data: { ok: true } });

        await expect(apiFetch("/api/v1/roles/me")).resolves.toEqual({
            ok: true,
        });

        // Hydration, then ONE authenticated request - no blind 401 first.
        expect(requests.map((request) => request.url)).toEqual([
            "/api/auth/session",
            "/api/v1/roles/me",
        ]);
        expect(requests[1].authorization).toBe("Bearer tok-1");
        expect(getAccessToken()).toBe("tok-1");
    });

    it("uses an in-memory token without a hydration round trip", async () => {
        setAccessToken("tok-9");
        respond = () => json({ data: { ok: true } });

        await apiFetch("/api/v1/roles/me");

        expect(sessionCalls()).toHaveLength(0);
        expect(requests).toHaveLength(1);
        expect(requests[0].authorization).toBe("Bearer tok-9");
    });

    it("does not re-hydrate after a 401 when hydration found no session", async () => {
        respond = (url) =>
            url === "/api/auth/session"
                ? json({ authenticated: false })
                : json({ detail: "Missing Authorization header" }, 401);

        await expect(apiFetch("/api/v1/roles/me")).rejects.toThrow(
            "Missing Authorization header",
        );

        // Hydration + the single request. The previous implementation fired the
        // request blind, absorbed a 401, then hydrated and retried.
        expect(sessionCalls()).toHaveLength(1);
        expect(requests).toHaveLength(2);
    });

    it("refreshes and retries once when an in-memory token is rejected", async () => {
        setAccessToken("stale-token");
        respond = (url, authorization) => {
            if (url === "/api/auth/refresh") {
                return json({
                    status: "authenticated",
                    accessToken: "fresh-token",
                });
            }
            return authorization === "Bearer fresh-token"
                ? json({ data: { ok: true } })
                : json({ detail: "Token expired" }, 401);
        };

        await expect(apiFetch("/api/v1/roles/me")).resolves.toEqual({
            ok: true,
        });

        expect(requests.map((request) => request.url)).toEqual([
            "/api/v1/roles/me",
            "/api/auth/refresh",
            "/api/v1/roles/me",
        ]);
        expect(requests[1].method).toBe("POST");
        expect(getAccessToken()).toBe("fresh-token");
    });
});

describe("in-flight GET deduplication", () => {
    it("coalesces concurrent identical GETs into one network request", async () => {
        setAccessToken("tok-1");
        respond = () => json({ data: { ok: true } });

        await expect(
            Promise.all([
                apiFetch("/api/v1/roles"),
                apiFetch("/api/v1/roles"),
            ]),
        ).resolves.toEqual([{ ok: true }, { ok: true }]);

        expect(
            requests.filter((request) => request.url === "/api/v1/roles"),
        ).toHaveLength(1);
    });

    it("keeps distinct query strings distinct", async () => {
        setAccessToken("tok-1");
        respond = () => json({ data: [] });

        await Promise.all([
            apiFetch("/api/v1/roles?limit=10"),
            apiFetch("/api/v1/roles?limit=20"),
        ]);

        expect(
            requests.filter((request) => request.url.startsWith("/api/v1/roles?")),
        ).toHaveLength(2);
    });

    it("never dedupes POSTs", async () => {
        setAccessToken("tok-1");
        respond = () => json({ data: { ok: true } });

        await Promise.all([
            apiPost("/api/v1/roles", {}),
            apiPost("/api/v1/roles", {}),
        ]);

        expect(
            requests.filter((request) => request.url === "/api/v1/roles"),
        ).toHaveLength(2);
    });

    it("does not reuse a settled GET", async () => {
        setAccessToken("tok-1");
        respond = () => json({ data: { ok: true } });

        await apiFetch("/api/v1/roles");
        await apiFetch("/api/v1/roles");

        expect(
            requests.filter((request) => request.url === "/api/v1/roles"),
        ).toHaveLength(2);
    });

    it("hydrates once when coalescing concurrent calls on a cold token", async () => {
        respond = (url) =>
            url === "/api/auth/session"
                ? json({
                      authenticated: true,
                      accessToken: "tok-1",
                      user: { id: "u1" },
                  })
                : json({ data: { ok: true } });

        await expect(
            Promise.all([
                apiFetch("/api/v1/roles/me"),
                apiFetch("/api/v1/roles/me"),
            ]),
        ).resolves.toEqual([{ ok: true }, { ok: true }]);

        // One hydration round trip and ONE data request - no 401-retry storm.
        expect(sessionCalls()).toHaveLength(1);
        expect(
            requests.filter((request) => request.url === "/api/v1/roles/me"),
        ).toHaveLength(1);
    });

    it("does not poison retries after a rejection", async () => {
        setAccessToken("tok-1");
        let failing = true;
        respond = () =>
            failing ? json({ detail: "boom" }, 500) : json({ data: { ok: true } });

        await expect(apiFetch("/api/v1/roles")).rejects.toThrow(ApiError);

        failing = false;
        await expect(apiFetch("/api/v1/roles")).resolves.toEqual({ ok: true });

        expect(
            requests.filter((request) => request.url === "/api/v1/roles"),
        ).toHaveLength(2);
    });
});