import { describe, expect, it } from "vitest";

import { COUNTRIES, getCountryByCode, matchPhoneCountry, splitDialCode } from "./countries";

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

  it("has no nested dial codes (longest-match stays unambiguous)", () => {
    const dials = COUNTRIES.flatMap((country) =>
      country.dialCode === null ? [] : [country.dialCode as string],
    );
    for (const a of dials) {
      for (const b of dials) {
        if (a !== b) expect(b.startsWith(a)).toBe(false);
      }
    }
  });
});

describe("matchPhoneCountry / splitDialCode", () => {
  it("splits spaced numbers, keeping the user's grouping in the rest", () => {
    const parsed = splitDialCode("+1 415 555 0101");
    expect(parsed?.country.code).toBe("US");
    expect(parsed?.rest).toBe("415 555 0101");
  });

  it("handles glued digits and punctuation", () => {
    expect(matchPhoneCountry("+14155550101")?.code).toBe("US");
    expect(splitDialCode("+14155550101")?.rest).toBe("4155550101");
    expect(matchPhoneCountry("+91-98765-43210")?.code).toBe("IN");
    expect(splitDialCode("+91 (98765) 43210")?.rest).toBe("(98765) 43210");
  });

  it("tie-breaks shared dial codes to the most common owner", () => {
    expect(matchPhoneCountry("+7 495 1234567")?.code).toBe("RU");
    expect(matchPhoneCountry("+44 20 7946 0958")?.code).toBe("GB");
    expect(matchPhoneCountry("+47 79 13 25 90")?.code).toBe("NO");
    expect(matchPhoneCountry("+358 18 12345")?.code).toBe("FI");
  });

  it("returns null without a leading + or with an unknown code", () => {
    expect(splitDialCode("4155550101")).toBeNull();
    expect(matchPhoneCountry("4155550101")).toBeNull();
    expect(splitDialCode("+999 1234567890")).toBeNull();
    expect(splitDialCode("")).toBeNull();
    expect(matchPhoneCountry("+not-a-number")).toBeNull();
  });

  it("trims whitespace around the stored value", () => {
    const parsed = splitDialCode("  +91 98765 43210 ");
    expect(parsed?.country.code).toBe("IN");
    expect(parsed?.rest).toBe("98765 43210");
  });
});
