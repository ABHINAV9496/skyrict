/**
 * Agents chat API client. Conversations are persisted in PostgreSQL via the
 * core monolith proxy → ai-agent service.
 */

import { apiDelete, apiFetch, apiPatch, apiPost } from "@/lib/api/http";

/** A conversation session with its metadata. */
export interface Conversation {
  id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  messages?: ChatMessage[];
}

/** A single message within a conversation. */
export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "agent";
  content: string;
  agent_name?: string | null;
  created_at: string;
}

export async function getConversations(): Promise<Conversation[]> {
  return apiFetch<Conversation[]>("/api/v1/agents/conversations");
}

export async function getConversation(id: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/v1/agents/conversations/${id}`);
}

export async function createConversation(input: {
  title?: string;
  first_prompt?: string;
}): Promise<Conversation> {
  return apiPost<Conversation>("/api/v1/agents/conversations", input);
}

export async function sendMessage(id: string, content: string): Promise<Conversation> {
  return apiPost<Conversation>(`/api/v1/agents/conversations/${id}`, { content });
}

export async function saveUserMessage(id: string, content: string): Promise<Conversation> {
  return apiPost<Conversation>(`/api/v1/agents/conversations/${id}`, {
    content,
    role: "user",
  });
}

export async function appendAgentMessage(id: string, content: string): Promise<Conversation> {
  return apiPost<Conversation>(`/api/v1/agents/conversations/${id}`, {
    content,
    role: "agent",
  });
}

export async function renameConversation(id: string, title: string): Promise<Conversation> {
  return apiPatch<Conversation>(`/api/v1/agents/conversations/${id}`, { title });
}

export async function setConversationPinned(id: string, pinned: boolean): Promise<Conversation> {
  return apiPatch<Conversation>(`/api/v1/agents/conversations/${id}`, { pinned });
}

export async function deleteConversation(id: string): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`/api/v1/agents/conversations/${id}`);
}
