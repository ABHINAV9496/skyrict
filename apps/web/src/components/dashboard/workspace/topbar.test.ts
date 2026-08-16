import { describe, expect, it } from "vitest";

import { resolvePageTitle } from "@/lib/page-title";

describe("resolvePageTitle", () => {
  it("resolves known workspace titles", () => {
    expect(resolvePageTitle("/dashboard")).toBe("Overview");
    expect(resolvePageTitle("/dashboard/erp")).toBe("Business Operations");
    expect(resolvePageTitle("/dashboard/agents")).toBe("AI Agents");
  });

  it("filters hyphenated UUID segments from the breadcrumb", () => {
    const orderId = "13071d6b-8434-460d-9aea-d894debbb8cf";
    expect(resolvePageTitle(`/dashboard/erp/orders/${orderId}`)).toBe(
      "Business Operations · Orders",
    );
    expect(resolvePageTitle(`/dashboard/erp/crm/customers/${orderId}`)).toBe(
      "Business Operations · Crm · Customers",
    );
  });

  it("keeps human-readable slugs in the breadcrumb", () => {
    expect(resolvePageTitle("/dashboard/erp/orders/acme-bulk-order")).toBe(
      "Business Operations · Orders · Acme Bulk Order",
    );
  });

  it("keeps short non-UUID segments", () => {
    expect(resolvePageTitle("/dashboard/agents/c/abc")).toBe("AI Agents · C · Abc");
  });
});
