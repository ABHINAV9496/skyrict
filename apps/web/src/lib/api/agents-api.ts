/**
 * Agents chat API client. Conversations live behind the stub /api/v1/agents/*
 * routes today; the client is shaped like a real API so swapping in the agents
 * service later is a one-line change per function.
 */

import { apiDelete, apiFetch, apiPatch, apiPost } from "@/lib/api/http";
import type { Conversation } from "@/lib/mock/agents-store";

export async function getConversations(): Promise<Conversation[]> {
  return apiFetch<Conversation[]>("/api/v1/agents/conversations");
}

export async function getConversation(id: string): Promise<Conversation> {
  return apiFetch<Conversation>(`/api/v1/agents/conversations/${id}`);
}

export async function createConversation(input: {
  title?: string;
  prompt?: string;
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

export async function setConversationPinned(id: string, pin: boolean): Promise<Conversation> {
  return apiPatch<Conversation>(`/api/v1/agents/conversations/${id}`, { pin });
}

export async function deleteConversation(id: string): Promise<{ deleted: boolean }> {
  return apiDelete<{ deleted: boolean }>(`/api/v1/agents/conversations/${id}`);
}
