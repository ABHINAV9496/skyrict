/**
 * Server-side pricing-currency resolution (SKY-40).
 *
 * Resolution order (server-only, never client-side):
 *   1. Legacy ``preferred_currency`` cookie - read for backward compatibility
 *      with sessions set before the manual switcher was removed; no UI writes
 *      it anymore (currency is 100% auto-detected in the beta).
 *   2. Platform geo headers (Vercel ``x-vercel-ip-country`` / Cloudflare
 *      ``cf-ipcountry``) mapped through the beta market table.
 *   3. ipapi.co reverse-geo fallback (bounded timeout, per-IP cache) when the
 *      platform did not attach a country header but a client IP is visible.
 *   4. ``usd`` - bots, localhost, and anything else degrade gracefully.
 *
 * ``available`` is the beta gate: it is False when the detected country is
 * outside the checkout allowlist (no wrong/USD pricing is rendered) or when
 * the market's price points are still pending approval (AED/SAR). The plan
 * page shows the region-blocked state instead; checkout is additionally
 * rejected server-side, so ``available`` is UX only - never a security
 * boundary.
 *
 * Always returns a supported currency; ``default`` is the guarantee for the
 * SSR first paint (resolved before render, so the page never flashes prices).
 */

import { cookies, headers } from "next/headers";

import type { BillingCurrency } from "@/lib/api/billing-api";
import {
    CURRENCY_COOKIE,
    CURRENCY_META,
    currencyFromCountry,
    isPricedCurrency,
    isSupportedCurrency,
} from "@/lib/billing/currency";

export interface PricingContext {
    currency: BillingCurrency;
    /** BCP-47 locale for rendering prices in the resolved currency. */
    locale: string;
    /** ISO 3166-1 alpha-2 country code, when reliably detected. */
    country: string | null;
    source: "cookie" | "header" | "geo" | "default";
    /**
     * False when the plan page must show the region-blocked state instead of
     * pricing: country outside the beta allowlist, or pricing still pending
     * for the resolved market (AED/SAR).
     */
    available: boolean;
}

/** Geo headers set by Vercel/Cloudflare on the proxy edge, best to worst. */
const COUNTRY_HEADERS = ["x-vercel-ip-country", "cf-ipcountry"] as const;

const GEO_TIMEOUT_MS = 1500;
const GEO_CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

/** In-memory cache of ipapi.co lookups keyed by client IP (bounded by TTL). */
const geoCache = new Map<string, { country: string; at: number }>();

function isLocalhostIp(ip: string): boolean {
    if (ip === "::1" || ip === "127.0.0.1") return true;
    if (ip.startsWith("10.") || ip.startsWith("192.168.")) return true;
    return /^172\.(1[6-9]|2\d|3[0-1])\./.test(ip);
}

/** Client IP from standard proxy headers; null when not attributable. */
function clientIp(headersList: Headers): string | null {
    for (const name of ["x-forwarded-for", "x-real-ip", "client-ip"]) {
        const raw = headersList.get(name);
        if (!raw) continue;
        const first = raw.split(",")[0]?.trim();
        if (first && !isLocalhostIp(first)) return first;
    }
    return null;
}

interface GeoLookup {
    country: string;
}

async function lookupGeo(ip: string): Promise<GeoLookup | null> {
    const cached = geoCache.get(ip);
    if (cached && Date.now() - cached.at < GEO_CACHE_TTL_MS) {
        return { country: cached.country };
    }
    try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), GEO_TIMEOUT_MS);
        const response = await fetch(`https://ipapi.co/${ip}/json/`, {
            signal: controller.signal,
            headers: { Accept: "application/json" },
            cache: "no-store",
        });
        clearTimeout(timer);
        if (!response.ok) return null;
        const payload = (await response.json()) as { country?: string };
        const country = payload.country ?? null;
        if (!country) return null;
        geoCache.set(ip, { country, at: Date.now() });
        return { country };
    } catch {
        // Timeout / network failure: fall through to the USD default.
        return null;
    }
}

/** Context for a detected country (header or reverse-geo). */
function contextForCountry(
    country: string,
    source: "header" | "geo",
): PricingContext {
    const code = country.trim().toUpperCase();
    const currency = currencyFromCountry(code);
    if (currency === null || !isPricedCurrency(currency)) {
        // Outside the beta allowlist, or the market's pricing is still
        // pending (AED/SAR): report the detection but flag the region so
        // the plan page renders the blocked state - never USD pricing.
        return {
            currency: "usd",
            locale: CURRENCY_META.usd.locale,
            country: code,
            source,
            available: false,
        };
    }
    return {
        currency,
        locale: CURRENCY_META[currency].locale,
        country: code,
        source,
        available: true,
    };
}

/** Resolve the pricing currency for the current request (server-only). */
export async function resolvePricingContext(): Promise<PricingContext> {
    // 1. Legacy manual-override cookie (no longer written by any UI).
    const store = await cookies();
    const preferred = store.get(CURRENCY_COOKIE)?.value;
    if (isSupportedCurrency(preferred)) {
        return {
            currency: preferred,
            locale: CURRENCY_META[preferred].locale,
            country: null,
            source: "cookie",
            available: isPricedCurrency(preferred),
        };
    }

    // 2. Platform country header.
    const headerList = await headers();
    for (const name of COUNTRY_HEADERS) {
        const country = headerList.get(name);
        if (!country) continue;
        return contextForCountry(country, "header");
    }

    // 3. Reverse-geo fallback (bounded, cached; skipped for localhost).
    const ip = clientIp(headerList);
    if (ip) {
        const lookup = await lookupGeo(ip);
        if (lookup) {
            return contextForCountry(lookup.country, "geo");
        }
    }

    // 4. Graceful default (bots, localhost, missing headers): USD stays the
    // neutral SSR guarantee when the region cannot be determined at all.
    return {
        currency: "usd",
        locale: CURRENCY_META.usd.locale,
        country: null,
        source: "default",
        available: true,
    };
}
