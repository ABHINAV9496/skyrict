import { describe, expect, it } from "vitest";

import { COUNTRIES } from "@/lib/hr/countries";
import { CURRENCIES, getCurrencyByCode } from "@/lib/hr/currencies";

describe("CURRENCIES", () => {
  it("derives one entry per unique currency code", () => {
    const expected = new Set(
      COUNTRIES.filter((c) => c.currency).map((c) => c.currency as string),
    );
    expect(new Set(CURRENCIES.map((c) => c.code))).toEqual(expected);
  });

  it("is sorted by code", () => {
    const sorted = [...CURRENCIES].sort((a, b) => a.code.localeCompare(b.code));
    expect(CURRENCIES).toEqual(sorted);
  });

  it("collects every country using a shared currency", () => {
    const eur = getCurrencyByCode("EUR");
    expect(eur).not.toBeNull();
    const expected = COUNTRIES.filter((c) => c.currency === "EUR").map(
      (c) => c.name,
    );
    expect(eur?.countries).toEqual([...expected].sort((a, b) => a.localeCompare(b)));
  });

  it("searches by member country name", () => {
    const inr = getCurrencyByCode("INR");
    expect(inr?.countries).toContain("India");
  });
});

describe("getCurrencyByCode", () => {
  it("round-trips known codes", () => {
    expect(getCurrencyByCode("USD")?.code).toBe("USD");
    expect(getCurrencyByCode("INR")?.code).toBe("INR");
  });

  it("returns null for unknown codes", () => {
    expect(getCurrencyByCode("XXY")).toBeNull();
    expect(getCurrencyByCode("")).toBeNull();
  });
});
