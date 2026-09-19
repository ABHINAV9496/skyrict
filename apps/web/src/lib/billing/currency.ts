import type { BillingCurrency } from "@/lib/api/billing-api";

/**
 * Currency/geo pricing config (SKY-40) — beta market allowlist.
 *
 * Checkout is restricted to exactly these markets for the beta; every other
 * country is region-blocked (see ``currencyFromCountry`` returning ``null``).
 * Prices are FIXED per-currency price points reviewed manually - they are
 * never derived from a live FX rate. The server-side catalog
 * (services/identity .../billing/plans.py) is authoritative; this module only
 * mirrors the allowlist + display metadata so the client can resolve the
 * currency to a locale and country detection can map country → currency.
 */

/** Beta checkout allowlist, in display order. Mirrors the backend catalog. */
export const SUPPORTED_CURRENCIES: readonly BillingCurrency[] = [
    "usd",
    "inr",
    "gbp",
    "eur",
    "aud",
    "cad",
    "sgd",
    "aed",
    "sar",
];

/**
 * Allowlisted markets whose fixed price points are not approved yet. They
 * resolve to their local currency for messaging but cannot check out (the
 * backend rejects them; there is NO USD catch-all) and the plan page shows
 * the region-expanding state instead of pricing.
 */
export const PRICING_PENDING_CURRENCIES: readonly BillingCurrency[] = [
    "aed",
    "sar"];

/** True when the currency has complete, business-approved price points. */
export function isPricedCurrency(code: BillingCurrency): boolean {
    return !PRICING_PENDING_CURRENCIES.includes(code);
}

/** Markets named in the region-blocked messaging (keep in sync above). */
export const BETA_MARKET_LABEL =
    "the United States, India, the United Kingdom, the European Union, Australia, Canada, Singapore, the UAE, and Saudi Arabia";

/** Display metadata per currency (BCP-47 locale + compact label). */
export const CURRENCY_META: Record<
    BillingCurrency,
    { locale: string; label: string }
> = {
    usd: { locale: "en-US", label: "USD — US $" },
    inr: { locale: "en-IN", label: "INR — India ₹" },
    gbp: { locale: "en-GB", label: "GBP — UK £" },
    eur: { locale: "de-DE", label: "EUR — Europe €" },
    aud: { locale: "en-AU", label: "AUD — Australia $" },
    cad: { locale: "en-CA", label: "CAD — Canada $" },
    sgd: { locale: "en-SG", label: "SGD — Singapore $" },
    aed: { locale: "en-AE", label: "AED — UAE د.إ" },
    sar: { locale: "ar-SA", label: "SAR — Saudi Arabia ﷼" },
};

/** Normalize an arbitrary currency string to the beta allowlist, else undefined. */
export function isSupportedCurrency(
    code: string | undefined | null,
): code is BillingCurrency {
    return SUPPORTED_CURRENCIES.includes(
        (code ?? "").trim().toLowerCase() as BillingCurrency,
    );
}

/** European Union member states (27) — one EUR pricing market for the beta. */
const EU_MEMBER_STATES = [
    "AT",
    "BE",
    "BG",
    "HR",
    "CY",
    "CZ",
    "DK",
    "EE",
    "FI",
    "FR",
    "DE",
    "GR",
    "HU",
    "IE",
    "IT",
    "LV",
    "LT",
    "LU",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
    "ES",
] as const;

/**
 * Country (ISO 3166-1 alpha-2, uppercase) → beta market currency. Countries
 * absent from this table are OUTSIDE the beta: checkout is unavailable and
 * the pricing page shows the region-blocked state. This is deliberately NOT
 * a full ISO world map — the beta allowlist is the point.
 */
export const COUNTRY_CURRENCY_MAP: Record<string, BillingCurrency> = {
    US: "usd",
    CA: "cad",
    IN: "inr",
    GB: "gbp",
    AU: "aud",
    SG: "sgd",
    AE: "aed",
    SA: "sar",
    ...Object.fromEntries(EU_MEMBER_STATES.map((code) => [code, "eur"])),
} as Record<string, BillingCurrency>;

/** Country code (uppercase alpha-2) → currency, `null` outside the beta. */
export function currencyFromCountry(
    country: string | null | undefined,
): BillingCurrency | null {
    const code = (country ?? "").trim().toUpperCase();
    return COUNTRY_CURRENCY_MAP[code] ?? null;
}

/** Cookie name for a legacy manual currency preference (read-only compat). */
export const CURRENCY_COOKIE = "preferred_currency";

/** Cookie lifetime (~1 year) for the persisted currency preference. */
export const CURRENCY_COOKIE_MAX_AGE = 60 * 60 * 24 * 365;
