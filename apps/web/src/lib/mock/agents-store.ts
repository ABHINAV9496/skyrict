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
  return [...conversations.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function getConversation(id: string): Conversation | undefined {
  return conversations.get(id);
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
