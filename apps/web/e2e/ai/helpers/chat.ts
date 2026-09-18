/*
 * Shared helpers for the AI journey specs (SKY-107).
 *
 * The stack runs the deterministic in-process MockProvider (AI_PROVIDER=mock),
 * so every agent answer begins with a known prefix and echoes the question it
 * was asked. These helpers navigate the real chat surface, submit a prompt,
 * and wait for the streamed answer to settle - no fixed sleeps.
 */

import { expect, type Locator, type Page } from "@playwright/test";

/** Stable prefix every MockProvider prose answer starts with (mirrors mock.py). */
export const MOCK_ANSWER_PREFIX =
    "Here is a summary based on the live data available to me.";

/** The newest agent message body (react-markdown container). */
export function latestAgentAnswer(page: Page): Locator {
    return page.locator(".chat-markdown").last();
}

/**
 * Wait for the newest agent bubble to finish streaming the mock answer and
 * optionally assert extra expected text (the echoed question, data line, ...).
 */
export async function waitForAgentAnswer(
    page: Page,
    expectedText?: string | RegExp,
): Promise<Locator> {
    const bubble = latestAgentAnswer(page);
    await expect(bubble).toContainText(MOCK_ANSWER_PREFIX);
    if (expectedText !== undefined) {
        await expect(bubble).toContainText(expectedText);
    }
    return bubble;
}

/** Assert the module label rendered above the newest agent answer. */
export async function expectAnsweringAgent(
    page: Page,
    displayName: string,
): Promise<void> {
    await expect(
        latestAgentAnswer(page).locator("xpath=.."),
    ).toContainText(displayName);
}

/** Start a brand-new conversation from the New Chat surface with one prompt. */
export async function askAgent(page: Page, question: string): Promise<Locator> {
    await page.goto("/dashboard/agents");
    const composer = page.getByRole("textbox", { name: "Message" });
    await expect(composer).toBeVisible();
    await composer.fill(question);
    await page.getByRole("button", { name: "Send message" }).click();
    // New Chat creates the conversation then routes to its stable URL.
    await page.waitForURL(/\/dashboard\/agents\/c\/[^/]+$/);
    return waitForAgentAnswer(page);
}

/** Send a follow-up prompt in the already-open conversation. */
export async function sendFollowUp(
    page: Page,
    question: string,
): Promise<Locator> {
    const composer = page.getByRole("textbox", { name: "Message" });
    await expect(composer).toBeEditable();
    await composer.fill(question);
    await page.getByRole("button", { name: "Send message" }).click();
    return waitForAgentAnswer(page);
}
