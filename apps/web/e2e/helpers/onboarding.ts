/*
 * Multi-tenant onboarding driver for the E2E harness.
 *
 * Drives the real signup wizard (signup surface, /register) end to end
 * through the browser: email step -> OTP verification -> password + text
 * CAPTCHA -> plan -> organization -> provisioning -> signin redirect.
 *
 * The identity service runs with ENVIRONMENT=test on the E2E stack, which is
 * the ONLY environment that returns the plaintext OTP (`code`) and the text
 * CAPTCHA answer. Both are captured from the BFF responses the browser already
 * receives, so no test-only endpoint is exercised and the wizard, its CSRF
 * gate, and tenant provisioning stay fully real. The same env flag disables
 * Turnstile, which makes the account step render a plain "I'm not a robot"
 * checkbox that runs the normal solve-captcha affordance on check.
 */

import { expect, type Page } from "@playwright/test";

import { fillOtp } from "./auth-flow";
import { signupUrl } from "../support/urls";

export interface RegisteredTenant {
    /** Slug the tenant was created under (also its subdomain). */
    slug: string;
    /** Tenant id returned by the create-organization BFF response. */
    tenantId: string;
    /** Owner email used to onboard the tenant. */
    email: string;
    /** Password chosen at the security step of the wizard. */
    password: string;
}

function uniqueSegment(): string {
    return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Walk the whole signup wizard and wait for the handoff to the new tenant's
 * sign-in surface. The page must be a fresh context page; it is left on
 * {slug}.signin.{apex}:{port}/signin?email=... so the caller can sign the
 * owner in next.
 */
export async function registerTenant(
    page: Page,
    input: {
        email: string;
        password: string;
        slug?: string;
        /** Submit a bogus CAPTCHA answer first and assert the gate rejects it. */
        rejectWrongCaptcha?: boolean;
    },
): Promise<RegisteredTenant> {
    const segment = uniqueSegment();
    const slug = input.slug ?? `e2e-${segment}`;
    const companyName = `E2E ${segment} Co`;

    // Attach the response captures BEFORE the wizard navigates: the verify step
    // calls /api/auth/code/send on mount and the security step fetches the
    // CAPTCHA as soon as it renders, so a late listener would miss both.
    let verificationCode: string | null = null;
    let captchaAnswer: string | null = null;
    let tenantId: string | null = null;
    page.on("response", async (response) => {
        const url = response.url();
        if (url.includes("/api/auth/code/send")) {
            const body = (await response.json().catch(() => ({}))) as {
                code?: string | null;
            };
            verificationCode = typeof body.code === "string" ? body.code : null;
        } else if (url.includes("/api/auth/captcha")) {
            const body = (await response.json().catch(() => ({}))) as {
                answer?: string | null;
            };
            captchaAnswer =
                typeof body.answer === "string" ? body.answer : null;
        } else if (url.includes("/api/auth/org")) {
            const body = (await response.json().catch(() => ({}))) as {
                tenantId?: string | null;
            };
            tenantId = typeof body.tenantId === "string" ? body.tenantId : null;
        }
    });

    /* ---------- account step ---------- */

    await page.goto(`${signupUrl()}/register`);
    await page.getByLabel("Work email").fill(input.email);
    await page
        .getByText("This email is available.")
        .waitFor({ timeout: 15_000 });
    // Without a Turnstile site key (ENVIRONMENT=test) the risk challenge is a
    // plain checkbox that runs the normal solve-captcha affordance on check.
    await page.getByRole("checkbox", { name: "I'm not a robot" }).check();
    await page.getByRole("button", { name: "Continue with email" }).click();
    await page.waitForURL("**/register/verify**");

    /* ---------- verify step (OTP auto-sent on mount) ---------- */

    // The plaintext OTP is only returned in ENVIRONMENT=test. The OTP form
    // submits itself as soon as the sixth digit is filled.
    await expect
        .poll(() => verificationCode, {
            timeout: 10_000,
            message:
                "Verification code was not returned by /api/auth/code/send.",
        })
        .toBeTruthy();
    await fillOtp(page, "Verification code", verificationCode ?? "");
    await page.waitForURL("**/register/security**");

    /* ---------- security step (password + text CAPTCHA) ---------- */

    await expect
        .poll(() => captchaAnswer, {
            timeout: 10_000,
            message: "Captcha answer was not returned by /api/auth/captcha.",
        })
        .toBeTruthy();
    await page.getByLabel("Password", { exact: true }).fill(input.password);
    await page
        .getByLabel("Confirm password", { exact: true })
        .fill(input.password);
    await page.getByLabel("Enter the code").fill(captchaAnswer ?? "");

    if (input.rejectWrongCaptcha) {
        // Prove the gate rejects a bogus answer BEFORE the wizard accepts the real
        // one: submit a mangled answer, expect the rejection copy, and wait for the
        // wizard to issue a fresh challenge. The listener below picks the new
        // answer up exactly when the re-mounted challenge input is committed (the
        // fetch runs in the new component's effect), so refilling targets the new
        // input - never the stale one that is about to be torn down.
        //
        // Playwright's expect.poll().toBeTruthy() narrows captchaAnswer to
        // never in the type system; capture a string-typed copy before the
        // poll assertion resets the control flow.
        const originalAnswer: string = captchaAnswer ?? "";
        const wrongAnswer = originalAnswer.endsWith("a")
            ? `${originalAnswer.slice(0, -1)}b`
            : `${originalAnswer}a`;
        await page.getByLabel("Enter the code").fill(wrongAnswer);
        await page.getByRole("button", { name: "Continue" }).click();
        // The rejection surfaces one of two copies. The normal path is the
        // backend 422 ("Unable to verify the security code. Try again."),
        // which is the STABLE signal; the client guard copy ("Enter the code
        // shown above to continue.") only appears when no code was committed,
        // and is cleared the instant the rotated challenge re-fetches
        // (onError(false)) - so asserting it alone is racy. Match either copy;
        // .first() avoids strict mode for the brief window where both render.
        await expect(
            page
                .getByText(
                    /Enter the code shown above to continue\.|Unable to verify the security code\. Try again\./,
                )
                .first(),
            "a wrong CAPTCHA answer must be rejected on the security step",
        ).toBeVisible({ timeout: 10_000 });
        await expect
            .poll(() => captchaAnswer, {
                timeout: 10_000,
                message:
                    "A wrong CAPTCHA answer must rotate to a fresh challenge.",
            })
            .not.toBe(originalAnswer);
        await page.getByLabel("Enter the code").fill(captchaAnswer ?? "");
    }

    await page.getByRole("button", { name: "Continue" }).click();
    await page.waitForURL("**/register/plan**");

    /* ---------- plan step ---------- */

    // Starter is $0; the driver picks it so the harness never touches billing.
    await page.getByRole("radio", { name: /Starter/ }).click();
    await page.getByRole("button", { name: "Continue with Starter" }).click();
    await page.waitForURL("**/register/organization**");

    /* ---------- organization step ---------- */

    await page.getByLabel("Company name").fill(companyName);
    // The slug auto-fills from the company name; overwrite it with the unique
    // tenant slug (the submit handler re-checks availability regardless).
    await page.getByLabel("Workspace URL").fill(slug);
    await page.getByText("This URL is available.").waitFor({ timeout: 15_000 });
    await page.locator("#industry").click();
    await page.getByRole("option", { name: "Technology" }).click();
    await page.getByLabel("Owner full name").fill("E2E Owner");
    // Phone/Business-location country scopes default to the browser timezone
    // (US in CI); only the number and address are filled below.
    await page.getByLabel("Phone number").fill("5550101234");
    await page.getByLabel("Street address").fill("1 Market St");
    await page.getByLabel("City").fill("San Francisco");
    await page.getByLabel("State / Province").fill("CA");
    await page.getByLabel("Postal code").fill("94103");
    await page
        .getByRole("checkbox", { name: /Terms of Service and Privacy Policy/ })
        .check();
    await page
        .getByRole("checkbox", {
            name: /authorized to set up this organization/,
        })
        .check();
    await page.getByRole("button", { name: "Create my workspace" }).click();

    await expect
        .poll(() => tenantId, {
            timeout: 10_000,
            message: "Tenant id was not returned by /api/auth/org.",
        })
        .toBeTruthy();

    // Creation triggers a provisioning screen (a ~10.4s sequence of timers) that
    // then hands off to {slug}.signin.{apex}:{port}/signin?email=... on its own.
    await page.waitForURL((url) => url.hostname.startsWith(`${slug}.signin.`), {
        timeout: 45_000,
    });

    return {
        slug,
        tenantId: tenantId ?? "",
        email: input.email,
        password: input.password,
    };
}
