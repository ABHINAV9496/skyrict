/*
 * Worker-scoped isolated-tenant fixture for the multi-tenant E2E harness.
 *
 * Each worker onboards a brand-new tenant through the REAL signup wizard
 * (see helpers/onboarding.ts), then signs the owner in through the real
 * signin surface and completes the mandatory MFA enrollment. The tenant is
 * fully real: its own subdomain, session family, reports catalog seed, and
 * sign-in flow. Worker isolation means tests can run in parallel without
 * sharing any auth state.
 *
 * The fixture exports a `tenant` test that provides ONLY the `tenant`
 * session. Specs that need the seeded default tenant's admin session should
 * import the `workspace` fixture from fixtures/auth.ts instead.
 */

import { expect, test as base, type BrowserContext, type Page } from "@playwright/test";

import {
  assertSessionReachesBff,
  enrollMfaAndFinish,
  installMfaSecretCapture,
  refreshSession,
  signInWithPassword,
  waitForWorkspaceSettled,
  whichMfaPath,
} from "../helpers/auth-flow";
import { registerTenant, type RegisteredTenant } from "../helpers/onboarding";
import { signinUrl, workspaceUrl } from "../support/urls";

export interface TenantSession {
  slug: string;
  context: BrowserContext;
  page: Page;
  /** Metadata of the tenant created through the onboarding wizard. */
  tenant: RegisteredTenant;
  refreshSession(): Promise<void>;
}

export const test = base.extend<{}, { tenant: TenantSession }>({
  tenant: [
    async ({ browser }, use) => {
      const segment = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
      const slug = `e2e-${segment}`;
      const email = `owner-${segment}@example.org`;
      const password = "E2e!Passw0rd-Strong-2026";

      const context = await browser.newContext({
        baseURL: workspaceUrl(slug),
        viewport: { width: 1280, height: 800 },
      });
      const page = await context.newPage();

      // 1. Onboard the tenant through the real wizard (leaves the page on the
      //    new tenant's sign-in surface).
      const tenant = await registerTenant(page, { email, password, slug });

      // 2. Sign the owner in; fresh tenancies always land on MFA enrollment
      //    (MFA is enforced at signup), so capture the setup secret first.
      const getMfaSecret = installMfaSecretCapture(page);
      await page.goto(`${signinUrl(slug)}/signin`);
      await signInWithPassword(page, email, password);
      const path = await whichMfaPath(page);
      expect(path, "Fresh tenants must take the MFA enrollment path.").toBe(
        "enrollment",
      );
      await enrollMfaAndFinish(page, { secretGetter: getMfaSecret });

      // 3. Workspace landed; let the shell finish its session hydration
      //    before the test's first navigation.
      await waitForWorkspaceSettled(page);

      // Fail fast here instead of inside the suite: prove the fresh tenant's
      // session also authenticates cookie-only BFF calls.
      await assertSessionReachesBff(page);

      const session: TenantSession = {
        slug,
        context,
        page,
        tenant,
        refreshSession: () => refreshSession(page),
      };
      await use(session);
      await context.close();
    },
    { scope: "worker" },
  ],
});