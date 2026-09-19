import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const cookiesStore = new Map<string, string>();
const requestHeaders = new Map<string, string>();

vi.mock("next/headers", () => ({
    cookies: async () => ({
        get: (name: string) => {
            const value = cookiesStore.get(name);
            return value === undefined ? undefined : { name, value };
        },
    }),
    headers: async () => {
        const nextHeaders = new Headers();
        for (const [key, value] of requestHeaders) {
            nextHeaders.set(key, value);
        }
        return nextHeaders;
    },
}));

import type { PricingContext } from "@/lib/server/geo";
import { resolvePricingContext } from "@/lib/server/geo";

function expectDefaults(context: PricingContext): void {
    expect(context.currency).toBe("usd");
    expect(context.locale).toBe("en-US");
    expect(context.country).toBeNull();
    expect(context.available).toBe(true);
}

beforeEach(() => {
    cookiesStore.clear();
    requestHeaders.clear();
    vi.restoreAllMocks();
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("resolvePricingContext", () => {
    it("honours a legacy manual cookie over geo headers (read-only compat)", async () => {
        cookiesStore.set("preferred_currency", "inr");
        requestHeaders.set("x-vercel-ip-country", "US");
        const context = await resolvePricingContext();
        expect(context.currency).toBe("inr");
        expect(context.locale).toBe("en-IN");
        expect(context.source).toBe("cookie");
        expect(context.available).toBe(true);
    });

    it("uses the Vercel country header when no cookie is set", async () => {
        requestHeaders.set("x-vercel-ip-country", "in");
        const context = await resolvePricingContext();
        expect(context.currency).toBe("inr");
        expect(context.locale).toBe("en-IN");
        expect(context.country).toBe("IN");
        expect(context.source).toBe("header");
        expect(context.available).toBe(true);
    });

    it("falls back to the Cloudflare header when Vercel is absent", async () => {
        requestHeaders.set("cf-ipcountry", "gb");
        const context = await resolvePricingContext();
        expect(context.currency).toBe("gbp");
        expect(context.source).toBe("header");
        expect(context.available).toBe(true);
    });

    it("maps new beta markets (AUD, CAD, SGD)", async () => {
        requestHeaders.set("x-vercel-ip-country", "AU");
        expect((await resolvePricingContext()).currency).toBe("aud");
        requestHeaders.set("x-vercel-ip-country", "CA");
        expect((await resolvePricingContext()).currency).toBe("cad");
        requestHeaders.set("x-vercel-ip-country", "SG");
        expect((await resolvePricingContext()).currency).toBe("sgd");
    });

    it("flags countries outside the beta allowlist as unavailable", async () => {
        requestHeaders.set("x-vercel-ip-country", "JP");
        const context = await resolvePricingContext();
        expect(context.available).toBe(false);
        expect(context.country).toBe("JP");
        // USD is a neutral carrier value here - the UI must render the
        // region-blocked state, never USD pricing as-if valid.
        expect(context.currency).toBe("usd");
        expect(context.source).toBe("header");
    });

    it("flags pricing-pending markets (AED/SAR) as unavailable", async () => {
        requestHeaders.set("x-vercel-ip-country", "AE");
        const context = await resolvePricingContext();
        expect(context.available).toBe(false);
        expect(context.country).toBe("AE");
        expect(context.source).toBe("header");
    });

    it("reverse-geos a public client IP as a last resort", async () => {
        requestHeaders.set("x-forwarded-for", "8.8.8.8");
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue({
                ok: true,
                json: async () => ({ country: "DE" }),
            }),
        );
        const context = await resolvePricingContext();
        expect(context.currency).toBe("eur");
        expect(context.country).toBe("DE");
        expect(context.source).toBe("geo");
        expect(context.available).toBe(true);
    });

    it("defaults to USD when reverse-geo fails or times out", async () => {
        requestHeaders.set("x-forwarded-for", "1.1.1.1");
        vi.stubGlobal(
            "fetch",
            vi.fn().mockRejectedValue(new Error("network down")),
        );
        const context = await resolvePricingContext();
        expectDefaults(context);
        expect(context.source).toBe("default");
    });

    it("ignores localhost client IPs and defaults to USD", async () => {
        requestHeaders.set("x-forwarded-for", "127.0.0.1");
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        const context = await resolvePricingContext();
        expectDefaults(context);
        expect(context.source).toBe("default");
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("defaults to USD with no cookie, headers, or client IP", async () => {
        const context = await resolvePricingContext();
        expectDefaults(context);
        expect(context.source).toBe("default");
    });
});
