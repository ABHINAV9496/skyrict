/*
 * AI journey: supervisor fallbacks and chat degradation (SKY-107, commit 5).
 *
 * The stack runs the deterministic MockProvider with AI_MOCK_BEHAVIOR=ok, so
 * this spec asserts the graceful behaviours that stay REACHABLE in that mode:
 *
 *   1. a bare greeting short-circuits to the supervisor greeting (never routed
 *      to a module, never sent to the provider);
 *   2. a real question that routes to no module is answered by the supervisor
 *      instead of a canned deflection;
 *   3. a failing chat stream surfaces a retryable error to the user and
 *      re-enables the composer (the BFF stream route is stubbed non-OK).
 *
 * The typed provider failures (AI_MOCK_BEHAVIOR=degrade_503 / rate_limit_429)
 * and the `not_provisioned` module path are intentionally NOT exercised here:
 * AI_MOCK_BEHAVIOR is fixed `ok` at compose-up for the whole job, and every
 * registry agent is enabled by the migrations, so neither path is reachable in
 * a fully seeded E2E stack. They stay covered by unit tests.
 */

import { expect, type Page } from "@playwright/test";

import { test } from "../fixtures/auth";

import {
    expectAnsweringAgent,
    latestAgentAnswer,
    MOCK_ANSWER_PREFIX,
    waitForAgentAnswer,
} from "./helpers/chat";

const GREETING_TEXT = "I'm the Skyrict assistant";
const STREAM_ENDPOINT = "**/api/v1/ai/agents/chat/stream";
const UNREACHABLE_TEXT = "The agent could not be reached. Please try again.";

/** Open the New Chat surface, submit one prompt, and land on the conversation. */
async function startChat(page: Page, prompt: string): Promise<void> {
    await page.goto("/dashboard/agents");
    const composer = page.getByRole("textbox", { name: "Message" });
    await expect(composer).toBeVisible();
    await composer.fill(prompt);
    await page
        .getByRole("button", { name: "Send message", exact: true })
        .click();
    // The workspace middleware strips the internal `/dashboard` prefix on
    // navigation, so the browser URL is the public `/agents/c/<id>`.
    await page.waitForURL(/\/agents\/c\/[^/]+$/);
}

test.describe("AI supervisor fallbacks and degradation", () => {
    test("greeting short-circuits to the supervisor", async ({ workspace }) => {
        const { page } = workspace;

        await startChat(page, "hello");

        const bubble = latestAgentAnswer(page);
        await expect(bubble).toContainText(GREETING_TEXT);
        await expectAnsweringAgent(page, "Supervisor");
        // A greeting never reaches a module agent (or the provider).
        await expect(bubble).not.toContainText(MOCK_ANSWER_PREFIX);
    });

    test("non-routed question is answered, not deflected", async ({
        workspace,
    }) => {
        const { page } = workspace;
        const question = "What is the best way to plan a team offsite?";

        await startChat(page, question);

        // The main provider answers as the supervisor: mock prose echoes the
        // real question, proving the request was not swallowed by a canned
        // abstention or a mis-routed module.
        const bubble = await waitForAgentAnswer(page, /You asked:/);
        await expect(bubble).toContainText(question);
        await expectAnsweringAgent(page, "Supervisor");
    });

    test("stream failure surfaces a retryable error and recovers", async ({
        workspace,
    }) => {
        const { page } = workspace;

        await page.route(STREAM_ENDPOINT, (route) =>
            route.fulfill({
                status: 503,
                contentType: "application/json",
                body: JSON.stringify({
                    detail: "Agent temporarily unavailable",
                }),
            }),
        );
        try {
            await startChat(page, "What is our current cash position?");

            // The stream client failed to reach the agent: the bubble shows the
            // retryable error instead of a hung typing indicator.
            await expect(page.getByText(UNREACHABLE_TEXT)).toBeVisible();

            // The composer recovered - it is editable and ready to send again
            // (not stuck in the "Stop generating" streaming state).
            const composer = page.getByRole("textbox", { name: "Message" });
            await expect(composer).toBeEditable();
            await composer.fill("Try again");
            await expect(
                page.getByRole("button", { name: "Send message", exact: true }),
            ).toBeEnabled();
        } finally {
            await page.unroute(STREAM_ENDPOINT);
        }
    });
});
