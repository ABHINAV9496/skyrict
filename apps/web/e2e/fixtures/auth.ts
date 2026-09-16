/*
 * Worker-scoped authenticated session fixture for the multi-tenant E2E
 * harness.
 *
 * Every worker gets ONE browser context that signs in as the seeded tenant
 * admin through the real signin surface (BFF login + mandatory MFA whatever
 * path it takes - challenge when already enrolled, fresh enrollment
 * otherwise). Because identity rotates the refresh token on every
 * /api/auth/session hydration and treats an already-rotated token as reuse
 * (revoking the whole session family), each worker walks its OWN token chain
 * inside a single context; never load the same storage-state snapshot into
 * two contexts (see playwright.config.ts).
 *
 * Tests receive the live `page` plus a `refreshSession()` handle that
 * re-hydrates through the BFF; a 401 interceptor keeps the jar's token
 * current across tests.
 */

import {
  expect,
  test as base,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import {
  completeMfaChallenge,
  enrollMfaAndFinish,
  installMfaSecretCapture,
  installSessionRefresh,
  readEnrolledSecret,
  refreshSession,
  signInWithPassword,
  whichMfaPath,
} from "../helpers/auth-flow";
import { signinUrl, workspaceUrl } from "../support/urls";

export interface AuthSession {
  /** Tenant slug the fixture authenticated against. */
  slug: string;
  context: BrowserContext;
  page: Page;
  /** Re-hydrate the session through the BFF (rotates the refresh token). */
  refreshSession(): Promise<void>;
}

const DEFAULT_SLUG = process.env.E2E_TENANT_SLUG ?? "default";

export const test = base.extend<{}, { workspace: AuthSession }>({
  workspace: [
    async ({ browser }, use) => {
      const slug = DEFAULT_SLUG;
      const email = process.env.E2E_ADMIN_EMAIL ?? "admin@skyrict.io";
      const password = process.env.E2E_ADMIN_PASSWORD ?? "Admin123!";
      const enrolledSecret = readEnrolledSecret();

      const context = await browser.newContext({
        baseURL: workspaceUrl(slug),
        viewport: { width: 1280, height: 800 },
      });
      const page = await context.newPage();

      // Capture the MFA setup response before sign-in: the setup-MFA page
      // calls the API on mount, so the fresh-enrollment arm below needs the
      // listener attached before the handoff happens. Harmless on the
      // challenge path.
      const getMfaSecret = installMfaSecretCapture(page);

      await page.goto(`${signinUrl(slug)}/signin`);
      await signInWithPassword(page, email, password);

      const path = await whichMfaPath(page);
      if (path === "challenge") {
        expect(
          enrolledSecret,
          "E2E_TOTP_SECRET must be set when the admin already has MFA enrolled.",
        ).toBeTruthy();
        await completeMfaChallenge(page, enrolledSecret);
      } else {
        await enrollMfaAndFinish(page, {
          secretGetter: getMfaSecret,
          knownSecret: enrolledSecret,
        });
      }

      // The page has landed on the workspace host; keep the jar's token
      // current from here on.
      installSessionRefresh(page);

      const session: AuthSession = {
        slug,
        context,
        page,
        refreshSession: () => refreshSession(page),
      };
      await use(session);
      await context.close();
    },
    { scope: "worker" },
  ],
});