import { describe, expect, it } from "vitest";

import { formatDate, formatMoney, formatNumber, formatPercent } from "@/lib/erp/money";

describe("formatMoney", () => {
  it("formats a number with the default currency", () => {
    expect(formatMoney(42000, "USD")).toBe("$42,000.00");
  });

  it("accepts numeric strings", () => {
    expect(formatMoney("87500", "USD")).toBe("$87,500.00");
  });

  it("honors the currency field", () => {
    expect(formatMoney(10, "EUR")).toContain("€");
  });

  it("defaults to USD when currency is missing", () => {
    expect(formatMoney(5, null)).toBe("$5.00");
  });

  it("renders an em dash for missing amounts", () => {
    expect(formatMoney(null, "USD")).toBe("—");
    expect(formatMoney(undefined, "USD")).toBe("—");
    expect(formatMoney("", "USD")).toBe("—");
  });

  it("renders an em dash for non-numeric input", () => {
    expect(formatMoney("not-a-number", "USD")).toBe("—");
  });
});

describe("formatNumber", () => {
  it("formats plain numbers", () => {
    expect(formatNumber(1234)).toBe("1,234");
  });

  it("accepts numeric strings", () => {
    expect(formatNumber("42.5")).toBe("42.5");
  });

  it("renders an em dash for missing or bad input", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber("oops")).toBe("—");
  });
});

describe("formatDate", () => {
  it("renders ISO dates in a readable format", () => {
    // Build the expectation from the same local-time Date so the assertion is
    // stable in every timezone (an absolute UTC instant can shift a day).
    const instant = new Date(2026, 6, 28, 12, 0, 0);
    expect(formatDate(instant.toISOString())).toBe(
      instant.toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      }),
    );
  });

  it("renders an em dash for missing dates", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
  });

  it("returns the raw value when it is not parseable", () => {
    expect(formatDate("soon")).toBe("soon");
  });
});

describe("formatPercent", () => {
  it("rounds to whole percentages", () => {
    expect(formatPercent(42.7)).toBe("43%");
  });

  it("renders an em dash for missing or bad input", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(Number.NaN)).toBe("—");
  });
});
