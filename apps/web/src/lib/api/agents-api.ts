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

/** Metadata for a file persisted on a message (blobs live in object
 *  storage; only this metadata round-trips through the API). */
export interface AttachmentMeta {
    id: string;
    name: string;
    type: string;
    size: number;
}

/** A single message within a conversation. */
export interface ChatMessage {
    id: string;
    conversation_id: string;
    role: "user" | "agent";
    content: string;
    agent_name?: string | null;
    attachments?: AttachmentMeta[];
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

export async function sendMessage(
    id: string,
    content: string,
): Promise<Conversation> {
    return apiPost<Conversation>(`/api/v1/agents/conversations/${id}`, {
        content,
    });
}

/** Persistable attachment payload sent to the BFF with a user message. */
export interface PersistAttachmentInput {
    id: string;
    name: string;
    type: string;
    size: number;
    base64: string;
}

export async function saveUserMessage(
    id: string,
    content: string,
    attachments?: PersistAttachmentInput[],
): Promise<Conversation> {
    return apiPost<Conversation>(`/api/v1/agents/conversations/${id}`, {
        content,
        role: "user",
        attachments,
    });
}

/** Server-relative URL for fetching a persisted attachment's blob. */
export function attachmentUrl(
    conversationId: string,
    attachmentId: string,
): string {
    return `/api/v1/agents/conversations/${conversationId}/attachments/${attachmentId}`;
}

export async function appendAgentMessage(
    id: string,
    content: string,
    agentName?: string,
): Promise<Conversation> {
    return apiPost<Conversation>(`/api/v1/agents/conversations/${id}`, {
        content,
        role: "agent",
        agent_name: agentName,
    });
}

export async function renameConversation(
    id: string,
    title: string,
): Promise<Conversation> {
    return apiPatch<Conversation>(`/api/v1/agents/conversations/${id}`, {
        title,
    });
}

export async function setConversationPinned(
    id: string,
    pinned: boolean,
): Promise<Conversation> {
    return apiPatch<Conversation>(`/api/v1/agents/conversations/${id}`, {
        pinned,
    });
}

export async function deleteConversation(
    id: string,
): Promise<{ deleted: boolean }> {
    return apiDelete<{ deleted: boolean }>(
        `/api/v1/agents/conversations/${id}`,
    );
}
