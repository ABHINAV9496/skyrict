import { describe, expect, it } from "vitest";

import type { BillingCurrency } from "@/lib/api/billing-api";
import {
    COUNTRY_CURRENCY_MAP,
    CURRENCY_COOKIE,
    CURRENCY_COOKIE_MAX_AGE,
    CURRENCY_META,
    PRICING_PENDING_CURRENCIES,
    SUPPORTED_CURRENCIES,
    currencyFromCountry,
    isPricedCurrency,
    isSupportedCurrency,
} from "@/lib/billing/currency";

describe("SUPPORTED_CURRENCIES", () => {
    it("allowlists exactly the nine beta markets", () => {
        expect(SUPPORTED_CURRENCIES).toEqual([
            "usd",
            "inr",
            "gbp",
            "eur",
            "aud",
            "cad",
            "sgd",
            "aed",
            "sar",
        ]);
    });

    it("has locale + label metadata for every currency", () => {
        for (const code of SUPPORTED_CURRENCIES) {
            expect(CURRENCY_META[code].locale).toMatch(/.+-.+/);
            expect(CURRENCY_META[code].label).toContain(code.toUpperCase());
        }
    });

    it("uses Indian numbering for INR and a eurozone locale for EUR", () => {
        expect(CURRENCY_META.inr.locale).toBe("en-IN");
        expect(CURRENCY_META.eur.locale).toBe("de-DE");
    });
});

describe("pricing tiers", () => {
    it("blocks checkout messaging for markets without approved prices", () => {
        expect(PRICING_PENDING_CURRENCIES).toEqual(["aed", "sar"]);
        expect(isPricedCurrency("aed")).toBe(false);
        expect(isPricedCurrency("sar")).toBe(false);
        const priced = SUPPORTED_CURRENCIES.filter(
            (code) => !PRICING_PENDING_CURRENCIES.includes(code),
        );
        for (const code of priced) {
            expect(isPricedCurrency(code as BillingCurrency)).toBe(true);
        }
    });
});

describe("isSupportedCurrency", () => {
    it("normalizes case, whitespace, and rejects unsupported codes", () => {
        expect(isSupportedCurrency("INR")).toBe(true);
        expect(isSupportedCurrency("  inr  ")).toBe(true);
        expect(isSupportedCurrency("eur")).toBe(true);
        expect(isSupportedCurrency("AUD")).toBe(true);
        expect(isSupportedCurrency("jpy")).toBe(false);
        expect(isSupportedCurrency("")).toBe(false);
        expect(isSupportedCurrency(undefined)).toBe(false);
        expect(isSupportedCurrency(null)).toBe(false);
    });
});

describe("currencyFromCountry", () => {
    it("maps the beta markets", () => {
        expect(currencyFromCountry("US")).toBe("usd");
        expect(currencyFromCountry("CA")).toBe("cad");
        expect(currencyFromCountry("IN")).toBe("inr");
        expect(currencyFromCountry("GB")).toBe("gbp");
        expect(currencyFromCountry("AU")).toBe("aud");
        expect(currencyFromCountry("SG")).toBe("sgd");
        expect(currencyFromCountry("AE")).toBe("aed");
        expect(currencyFromCountry("SA")).toBe("sar");
        expect(currencyFromCountry("DE")).toBe("eur");
    });

    it("normalizes header-style lowercase codes", () => {
        expect(currencyFromCountry("in")).toBe("inr");
        expect(currencyFromCountry(" de ")).toBe("eur");
    });

    it("returns null for countries outside the beta (no USD catch-all)", () => {
        expect(currencyFromCountry("JP")).toBeNull();
        expect(currencyFromCountry("BR")).toBeNull();
        expect(currencyFromCountry("XX")).toBeNull();
        expect(currencyFromCountry(null)).toBeNull();
        expect(currencyFromCountry(undefined)).toBeNull();
    });

    it("maps every EU member state (including non-eurozone) to EUR", () => {
        const eu = [
            "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
            "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
            "PL", "PT", "RO", "SE", "SI", "SK", "ES",
        ];
        expect(eu).toHaveLength(27);
        for (const country of eu) {
            expect(COUNTRY_CURRENCY_MAP[country]).toBe("eur");
        }
    });
});

describe("currency cookie", () => {
    it("keeps the legacy cookie name and a ~1 year lifetime", () => {
        expect(CURRENCY_COOKIE).toBe("preferred_currency");
        expect(CURRENCY_COOKIE_MAX_AGE).toBe(60 * 60 * 24 * 365);
    });
});
