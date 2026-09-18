/*
 * Billing E2E smoke (SKY-36).
 *
 * Uses the worker-scoped `tenant` fixture: a fresh tenancy onboarded through
 * the real wizard lands on Starter with an active trial, so it is the
 * canonical trialing workspace for the banner and plans-page assertions.
 *
 * Runs as ONE test with steps (single context, single refresh-token
 * rotation chain - see the reports-workspace.spec.ts header):
 *   1. trial countdown banner on the workspace shell + CTA to Plans
 *   2. plans page renders the real subscription and server catalog
 *      (Starter current; Professional/Business purchasable; Enterprise
 *      contact-sales), Monthly/Annual toggle swaps prices
 *   3. checkout without Stripe configured -> the REAL backend 503 chain
 *      surfaces the sanitized "Stripe is not configured" message
 *   4. checkout with only the external Stripe redirect boundary stubbed
 *      -> the browser actually redirects to the session URL
 *   5. portal without a Stripe customer -> REAL backend 402 surfaces
 *
 * Steps 3 and 5 are un-stubbed end-to-end paths through web -> BFF ->
 * identity; only the external Stripe host is faked (step 4).
 */

import { expect } from "@playwright/test";
import { test } from "./fixtures/tenants";
import { workspaceUrl } from "./support/urls";

const BILLING_PATH = "/dashboard/settings/billing";
const CHECKOUT_URL = "https://checkout.stripe.com/c/pay/cs_test_skyrict";

test("billing: trial banner, plans catalog, checkout + portal flows", async ({
  tenant,
}) => {
  const { slug, page } = tenant;

  await test.step("trial banner shows on the workspace shell and links to Plans", async () => {
    await expect(
      page.getByText(/You're on a free trial - your trial ends in \d+ days/),
    ).toBeVisible({ timeout: 20_000 });
    await page.getByRole("link", { name: "Choose a plan" }).click();
    await page.waitForURL(`**${BILLING_PATH}`);
  });

  const starterCard = page.locator('section[aria-label="Starter plan"]');
  const professionalCard = page.locator('section[aria-label="Professional plan"]');
  const businessCard = page.locator('section[aria-label="Business plan"]');
  const enterpriseCard = page.locator('section[aria-label="Enterprise plan"]');

  await test.step("plans page renders the subscription and server catalog", async () => {
    await expect(page.getByRole("heading", { name: "Plans" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Current plan" }),
    ).toBeVisible();
    // Fresh tenancy: Starter + trialing.
    await expect(
      page.getByText(/Starter trial - your trial ends in \d+ days/),
    ).toBeVisible();

    // Annual is the default; Professional $24, Business $66 (per-workspace
    // monthly-equivalent, billed yearly).
    await expect(starterCard.getByText("Current")).toBeVisible();
    await expect(starterCard.getByText("Free")).toBeVisible();
    await expect(professionalCard.getByText("$24")).toBeVisible();
    await expect(
      professionalCard.getByText(/\/ month, billed yearly/),
    ).toBeVisible();
    await expect(
      professionalCard.getByRole("button", { name: "Choose Professional" }),
    ).toBeVisible();
    await expect(businessCard.getByText("$66")).toBeVisible();
    await expect(
      businessCard.getByRole("button", { name: "Choose Business" }),
    ).toBeVisible();
    await expect(enterpriseCard.getByText("Custom")).toBeVisible();
    await expect(
      enterpriseCard.getByRole("link", { name: "Contact sales" }),
    ).toBeVisible();

    // Monthly toggle swaps to the monthly prices.
    await page.getByRole("button", { name: "Monthly" }).click();
    await expect(professionalCard.getByText("$29")).toBeVisible();
    await expect(businessCard.getByText("$79")).toBeVisible();
    await page.getByRole("button", { name: "Annual" }).click();
    await expect(professionalCard.getByText("$24")).toBeVisible();
  });

  await test.step("checkout without Stripe -> sanitized 503 in the UI", async () => {
    // The e2e stack runs identity with no Stripe keys, so this is the real
    // web -> BFF -> identity -> 503 problem+json -> UI error chain.
    await professionalCard
      .getByRole("button", { name: "Choose Professional" })
      .click();
    await expect(
      page.getByText("Stripe is not configured").first(),
    ).toBeVisible({ timeout: 20_000 });
    await expect(
      page.getByText("The checkout session could not be started."),
    ).toBeVisible();
  });

  await test.step("checkout redirects to the Stripe-hosted session", async () => {
    // Stub ONLY the external boundary: the session-creation call becomes a
    // real Stripe checkout URL and the Stripe host is resolved by a stub
    // HTML page so the redirect navigation completes deterministically.
    await page.route("**/api/v1/billing/checkout-session*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          data: { session_id: "cs_test_skyrict", url: CHECKOUT_URL },
        }),
      }),
    );
    await page.route("https://checkout.stripe.com/**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body>Stripe checkout stub</body></html>",
      }),
    );
    try {
      await businessCard
        .getByRole("button", { name: "Choose Business" })
        .click();
      await page.waitForURL("https://checkout.stripe.com/**");
      expect(page.url()).toContain("checkout.stripe.com");
    } finally {
      await page.unroute("**/api/v1/billing/checkout-session*");
      await page.unroute("https://checkout.stripe.com/**");
    }

    // Back on the workspace for the portal probe.
    await page.goto(`${workspaceUrl(slug)}${BILLING_PATH}`);
    await expect(page.getByRole("heading", { name: "Plans" })).toBeVisible();
  });

  await test.step("manage billing without a Stripe customer -> 402 in the UI", async () => {
    // The fresh tenant has never checked out (no Stripe customer), so the
    // real portal-session path returns the 402 chain end to end.
    await page.getByRole("button", { name: "Manage billing" }).click();
    await expect(
      page
        .getByText("An active subscription is required to manage billing settings")
        .first(),
    ).toBeVisible({ timeout: 20_000 });
  });
});