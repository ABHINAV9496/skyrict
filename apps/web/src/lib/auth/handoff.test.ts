import { describe, expect, it } from "vitest";

import { soleRoleDestination } from "@/lib/auth/handoff";

describe("soleRoleDestination", () => {
  it("returns /leave for exactly [employee_self_service]", () => {
    expect(soleRoleDestination(["employee_self_service"])).toBe("/leave");
  });

  it("returns / for empty roles", () => {
    expect(soleRoleDestination([])).toBe("/");
  });

  it("returns / when multiple roles include employee_self_service", () => {
    expect(
      soleRoleDestination(["employee_self_service", "hr_admin"]),
    ).toBe("/");
  });

  it("returns / for non-portal roles", () => {
    expect(soleRoleDestination(["tenant_owner"])).toBe("/");
  });

  it("returns / for a variant spelling", () => {
    expect(soleRoleDestination(["Employee Self Service"])).toBe("/");
  });
});
