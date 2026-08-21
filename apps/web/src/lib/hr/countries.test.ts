import { describe, expect, it } from "vitest";

import { COUNTRIES, getCountryByCode } from "./countries";

describe("COUNTRIES dataset", () => {
  it("has unique uppercase alpha-2 codes and is sorted by name", () => {
    const codes = COUNTRIES.map((country) => country.code);
    expect(codes.length).toBeGreaterThan(200);
    expect(new Set(codes).size).toBe(codes.length);
    for (const code of codes) {
      expect(code).toMatch(/^[A-Z]{2}$/);
    }
    const names = COUNTRIES.map((country) => country.name);
    expect([...names].sort((a, b) => a.localeCompare(b))).toEqual(names);
  });

  it("carries the merged CSV fields for the United States", () => {
    const us = getCountryByCode("US");
    expect(us).toEqual({
      code: "US",
      name: "United States",
      currency: "USD",
      dialCode: "1",
      phoneMin: 10,
      phoneMax: 10,
    });
  });

  it("applies the CLDR name overrides", () => {
    expect(getCountryByCode("GB")?.name).toBe("United Kingdom");
  });

  it("takes the first currency when the CSV lists several (Bhutan)", () => {
    const bhutan = getCountryByCode("BT");
    expect(bhutan?.currency).toBe("INR");
  });

  it("uses explicit nulls for territories without data (Antarctica)", () => {
    const antarctica = getCountryByCode("AQ");
    expect(antarctica).toBeDefined();
    expect(antarctica?.currency).toBeNull();
    expect(antarctica?.dialCode).toBeNull();
    expect(antarctica?.phoneMin).toBeNull();
    expect(antarctica?.phoneMax).toBeNull();
  });

  it("keeps every currency a 3-letter code and phone ranges consistent", () => {
    for (const country of COUNTRIES) {
      if (country.currency !== null) {
        expect(country.currency).toMatch(/^[A-Z]{3}$/);
      }
      if (country.phoneMin !== null && country.phoneMax !== null) {
        expect(country.phoneMin).toBeLessThanOrEqual(country.phoneMax);
        expect(country.phoneMin).toBeGreaterThan(0);
      }
    }
  });
});
