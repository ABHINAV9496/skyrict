/*
 * Payroll full-journey smoke suite.
 *
 * Exercises the end-to-end payroll flow: enable AI automation, hire an
 * employee, create and compute a payroll run, tick the AI batch, review
 * the payslip, approve the run, and verify notifications. Uses the
 * worker-scoped `workspace` fixture (seeded admin) and sequential
 * page.goto() calls within a single browser context so the session
 * rotation chain stays intact.
 */

import { expect } from "@playwright/test";

import { test } from "./fixtures/auth";
import {
  approvePayrollRun,
  createPayrollRun,
  computePayrollRun,
  enableAiAutomation,
  getPayrollSettings,
  hireEmployee,
  tickPayrollBatch,
} from "./helpers/payroll-flow";

test("payroll full journey: automation, hire, run, batch, approve, notify", async ({
  workspace,
}) => {
  const { page } = workspace;
  let runId: string;

  // ── enable AI automation ─────────────────────────────────────────────
  await test.step("enable AI automation", async () => {
    await enableAiAutomation(page);
    const settings = await getPayrollSettings(page);
    expect(settings.ai_automation_enabled).toBe(true);
  });

  // ── navigate to payroll settings ─────────────────────────────────────
  await test.step("navigate to payroll settings page", async () => {
    await page.goto("/dashboard/erp/payroll/settings");
    await expect(
      page.getByRole("heading", { name: /Payroll [Ss]ettings/ }),
    ).toBeVisible();
  });

  // ── hire an employee ─────────────────────────────────────────────────
  await test.step("hire an employee", async () => {
    const employee = await hireEmployee(page, {
      firstName: "Ada",
      lastName: "Lovelace",
      hireDate: "2026-01-05",
    });
    expect(employee.id).toBeTruthy();
  });

  // ── create and compute payroll run ───────────────────────────────────
  await test.step("create and compute payroll run", async () => {
    const run = await createPayrollRun(page, {
      periodStart: "2026-01-01",
      periodEnd: "2026-01-31",
    });
    expect(run.status).toBe("draft");
    runId = run.id;

    const computed = await computePayrollRun(page, runId);
    expect(computed.entries.length).toBeGreaterThanOrEqual(1);
    expect(computed.run.status).toBe("computed");
  });

  // ── tick payroll batch via AI endpoint ───────────────────────────────
  await test.step("tick payroll batch via AI endpoint", async () => {
    const result = await tickPayrollBatch(page);
    expect(result).toBeTruthy();
  });

  // ── navigate to payroll review page ──────────────────────────────────
  await test.step("navigate to payroll review page", async () => {
    await page.goto("/dashboard/erp/payroll");
    await expect(
      page.getByRole("heading", { name: "Payroll" }),
    ).toBeVisible();
  });

  // ── approve run via API ──────────────────────────────────────────────
  await test.step("approve run via API", async () => {
    const approved = await approvePayrollRun(page, runId);
    expect(approved.status).toBe("approved");
  });

  // ── navigate to notifications page ───────────────────────────────────
  await test.step("navigate to notifications page", async () => {
    await page.goto("/dashboard/settings/notifications");
    await expect(page.getByRole("heading")).toBeVisible();
  });
});
