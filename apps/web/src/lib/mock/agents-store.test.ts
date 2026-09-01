import { beforeEach, describe, expect, it } from "vitest";

import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  renameConversation,
  togglePinConversation,
} from "@/lib/mock/agents-store";

const getStore = () =>
  (globalThis as unknown as { __agentsConversations: Map<string, unknown> })
    .__agentsConversations;

beforeEach(() => {
  // Clear the shared map in place (the module holds a live reference; the
  // store persists on globalThis across HMR/test-files).
  getStore().clear();
});

/** Small settle so ISO timestamps (updatedAt) differ between rows. */
function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 2));
}

describe("agents-store conversation management", () => {
  it("renames a conversation and truncates long titles", () => {
    const conv = createConversation("Draft", "Need a plan");
    const renamed = renameConversation(conv.id, "Quarterly plan");
    expect(renamed?.title).toBe("Quarterly plan");
    expect(getConversation(conv.id)?.title).toBe("Quarterly plan");

    // Matches the store's title convention: 57 chars + ellipsis = 58 visible.
    const long = renameConversation(conv.id, "x".repeat(120));
    expect(long?.title).toHaveLength(58);
    expect(long?.title.endsWith("…")).toBe(true);
  });

  it("ignores a blank rename", () => {
    const conv = createConversation("Draft", "hello");
    const result = renameConversation(conv.id, "   ");
    expect(result?.title).toBe("hello");
    expect(getConversation(conv.id)?.title).toBe("hello");
  });

  it("toggles the pinned flag on and off", () => {
    const conv = createConversation("Draft", "hello");
    expect(togglePinConversation(conv.id)?.pinned).toBe(true);
    expect(togglePinConversation(conv.id)?.pinned).toBe(false);
  });

  it("deletes a conversation", () => {
    const conv = createConversation("Draft", "hello");
    expect(getConversation(conv.id)).toBeDefined();
    expect(deleteConversation(conv.id)).toBe(true);
    expect(getConversation(conv.id)).toBeUndefined();
    expect(deleteConversation(conv.id)).toBe(false);
  });

  it("lists pinned conversations first, then by recency", async () => {
    const first = createConversation("Pinned chat", "first");
    await tick();
    const second = createConversation("Active chat", "second");
    await tick();
    const third = createConversation("Older chat", "third");
    await tick();

    togglePinConversation(first.id);

    const ids = listConversations().map((c) => c.id);
    // first is pinned → jumps ahead; the rest are ordered by updatedAt desc.
    expect(ids).toEqual([first.id, third.id, second.id]);
  });
});