/**
 * In-memory store for the AI Agents chat world.
 *
 * This is a frontend stub: conversations live in a module-level Map on the
 * server and reset when the process restarts. It exists so the chat UI can be
 * built against real route shapes (`GET /api/v1/agents/conversations`, etc.)
 * and later pointed at an agents service without changing the client.
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

const conversations = new Map<string, Conversation>();

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
    title: title.trim() || "New chat",
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
  if (conversation.messages.length === 2 && role === "agent") {
    conversation.title = conversation.messages[0].content.slice(0, 48) || conversation.title;
  }
  return conversation;
}
