/**
 * In-memory store for the AI Agents chat world.
 *
 * Conversations live on `globalThis` so they survive Next.js hot-module
 * replacement during development.  The store is a stub: it lets the chat UI
 * be built against real route shapes (`GET /api/v1/agents/conversations`,
 * etc.) and can be swapped for a real agents service later with a one-line
 * change per function.
 */

export type ChatRole = "user" | "agent";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  /** True when the conversation is pinned to the top of the sidebar list. */
  pinned?: boolean;
  messages: ChatMessage[];
}

function newId(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

// Persist across HMR so conversations don't vanish on every code change.
const g = globalThis as unknown as { __agentsConversations?: Map<string, Conversation> };
if (!g.__agentsConversations) g.__agentsConversations = new Map();
const conversations = g.__agentsConversations;

/** Derive a short title from the first user message (max 60 chars). */
function deriveTitle(prompt: string): string {
  const cleaned = prompt.replace(/\s+/g, " ").trim();
  if (!cleaned) return "New chat";
  return cleaned.length > 60 ? `${cleaned.slice(0, 57)}…` : cleaned;
}

export function listConversations(): Conversation[] {
  return [...conversations.values()].sort(
    (a, b) =>
      Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) ||
      b.updatedAt.localeCompare(a.updatedAt),
  );
}

export function getConversation(id: string): Conversation | undefined {
  return conversations.get(id);
}

/** Rename a conversation. Returns the updated conversation or undefined. */
export function renameConversation(
  id: string,
  title: string,
): Conversation | undefined {
  const conversation = conversations.get(id);
  const trimmed = title.trim();
  if (!conversation || !trimmed) return conversation;
  conversation.title = trimmed.length > 60 ? `${trimmed.slice(0, 57)}…` : trimmed;
  conversation.updatedAt = new Date().toISOString();
  return conversation;
}

/** Toggle a conversation's pinned state. Returns the updated conversation or undefined. */
export function togglePinConversation(id: string): Conversation | undefined {
  const conversation = conversations.get(id);
  if (!conversation) return undefined;
  conversation.pinned = !conversation.pinned;
  conversation.updatedAt = new Date().toISOString();
  return conversation;
}

/** Delete a conversation. Returns true when a conversation was removed. */
export function deleteConversation(id: string): boolean {
  return conversations.delete(id);
}

export function createConversation(title: string, firstPrompt?: string): Conversation {
  const now = new Date().toISOString();
  const conversation: Conversation = {
    id: newId(),
    title: firstPrompt?.trim() ? deriveTitle(firstPrompt) : title.trim() || "New chat",
    createdAt: now,
    updatedAt: now,
    messages: [],
  };
  conversations.set(conversation.id, conversation);
  if (firstPrompt?.trim()) {
    appendMessage(conversation.id, "user", firstPrompt);
  }
  return conversations.get(conversation.id)!;
}

export function appendMessage(
  id: string,
  role: ChatRole,
  content: string,
): Conversation | undefined {
  const conversation = conversations.get(id);
  if (!conversation) return undefined;
  const message: ChatMessage = {
    id: newId(),
    role,
    content,
    createdAt: new Date().toISOString(),
  };
  conversation.messages.push(message);
  conversation.updatedAt = message.createdAt;
  // Auto-title from first user message (after the initial prompt).
  if (conversation.messages.length === 2 && role === "agent") {
    conversation.title = deriveTitle(conversation.messages[0].content);
  }
  return conversation;
}
