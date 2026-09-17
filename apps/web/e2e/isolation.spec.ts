/*
 * Two-tenant RLS isolation E2E spec.
 *
 * Creates a product in the seeded default tenant (tenant A), registers a
 * fresh tenant B mid-test, signs in, and verifies tenant B cannot see
 * tenant A's product — proving row-level security isolates tenants.
 */

import { expect, type BrowserContext, type Page } from "@playwright/test";

import { test } from "./fixtures/auth";
import { registerTenant } from "./helpers/onboarding";
import {
  signInWithPassword,
  whichMfaPath,
  enrollMfaAndFinish,
  installMfaSecretCapture,
  waitForWorkspaceSettled,
} from "./helpers/auth-flow";
import { createProduct, uniqueRef, listProducts } from "./helpers/inventory-flow";
import { workspaceUrl, signinUrl } from "./support/urls";

test("two-tenant RLS isolation: product in tenant A is invisible to tenant B", async ({ workspace, browser }) => {
  const { page } = workspace;
  const segment = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const newSlug = `e2e-isol-${segment}`;
  const email = `isol-${segment}@example.org`;
  const password = "E2e!Passw0rd-Isol-2026";
  let sku: string;
  let newContext: BrowserContext | undefined;
  let newPage: Page | undefined;

  try {
    await test.step("create a product in the default tenant", async () => {
      sku = uniqueRef("ISOL-A");
      await createProduct(page, { sku, name: "Isolation Test Product" });
    });

    await test.step("register tenant B", async () => {
      newContext = await browser.newContext({
        baseURL: workspaceUrl(newSlug),
        viewport: { width: 1280, height: 800 },
      });
      newPage = await newContext.newPage();
      await registerTenant(newPage, { email, password, slug: newSlug });
    });

    await test.step("sign in to tenant B", async () => {
      const getMfaSecret = installMfaSecretCapture(newPage!);
      await newPage!.goto(`${signinUrl(newSlug)}/signin`);
      await signInWithPassword(newPage!, email, password);
      const path = await whichMfaPath(newPage!);
      expect(path).toBe("enrollment");
      await enrollMfaAndFinish(newPage!, { secretGetter: getMfaSecret });
      await waitForWorkspaceSettled(newPage!);
    });

    await test.step("verify tenant B cannot see tenant A's product", async () => {
      const products = await listProducts(newPage!);
      const skus = products.data.map((p) => p.sku as string);
      expect(skus).not.toContain(sku);
    });
  } finally {
    await newContext?.close();
  }
});
