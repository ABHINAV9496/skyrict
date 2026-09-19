/*
 * AI journey: chat streaming + composer (SKY-107, commit 1).
 *
 * Drives the real supervisor SSE pipeline end to end against the
 * deterministic MockProvider (AI_PROVIDER=mock): a routed inventory question
 * streams a labelled answer, the composer returns to a usable state, and a
 * follow-up turn appends to the same conversation. No paid LLM is called.
 */

import { expect } from "@playwright/test";

import { test } from "../fixtures/auth";
import {
    askAgent,
    expectAnsweringAgent,
    sendFollowUp,
} from "./helpers/chat";

test.describe("AI chat streaming", () => {
    test("streams a classified inventory answer and settles the composer", async ({
        workspace,
    }) => {
        const { page } = workspace;
        const question = "Do we have any products below reorder point?";

        const answer = await askAgent(page, question);

        await expectAnsweringAgent(page, "Inventory Monitor");
        await expect(answer).toContainText(question);
        // The turn completed: the composer is back to its idle send state.
        await expect(
            page.getByRole("button", { name: "Send message", exact: true }),
        ).toBeVisible();
    });

    test("keeps the same conversation streaming for a follow-up turn", async ({
        workspace,
    }) => {
        const { page } = workspace;

        await askAgent(page, "What is our stock on hand?");
        const followUp = "Show the warehouse breakdown";
        const answer = await sendFollowUp(page, followUp);

        await expect(answer).toContainText(followUp);
        // Two user turns => two streamed agent answers in this conversation.
        await expect(page.locator(".chat-markdown")).toHaveCount(2);
    });
});
