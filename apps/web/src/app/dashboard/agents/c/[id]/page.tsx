"use client";

import { useEffect, useRef, useState } from "react";
import { notFound } from "next/navigation";

import { AgentsHeader } from "@/components/dashboard/agents/agents-header";
import { ChatComposer } from "@/components/dashboard/agents/chat-composer";
import { MessageList } from "@/components/dashboard/agents/chat-message-list";
import { ChatSkeleton } from "@/components/ui/page-skeletons";
import { getConversation } from "@/lib/api/agents-api";
import { useSession } from "@/lib/auth/session";
import { useAgentChat, type AgentChatMessage } from "@/lib/chat/use-agent-chat";
import type { ChatMessage, Conversation } from "@/lib/mock/agents-store";

function toAgentMessage(message: ChatMessage): AgentChatMessage {
  return { ...message, agentName: null, citations: [], failed: false };
}

/**
 * The live conversation view. The first prompt (arriving from the New Chat
 * suggestion) is answered automatically by streaming one real supervisor turn;
 * every subsequent send streams too. Conversations remain in the mock store
 * for navigation/history — SKY-60 replaces SIMULATED ANSWERS with real ones,
 * not the sidebar.
 */
function ConversationView({ conversation }: { conversation: Conversation }) {
  const { user } = useSession();
  const { messages, sending, activeAgent, send, stop } = useAgentChat(
    conversation.messages.map(toAgentMessage),
  );
  const autoStarted = useRef(false);

  useEffect(() => {
    if (autoStarted.current || sending) return;
    const last = conversation.messages[conversation.messages.length - 1];
    if (last && last.role === "user") {
      autoStarted.current = true;
      void send(last.content);
    }
  }, [conversation.messages, send, sending]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <AgentsHeader title={conversation.title} />
      <MessageList messages={messages} userDisplay={user?.fullName ?? user?.email ?? ""} />
      <div className="shrink-0 px-4 pb-4 pt-2 md:pb-6">
        <ChatComposer
          onSend={send}
          onStop={sending ? stop : undefined}
          placeholder="Continue the conversation…"
        />
      </div>
      {activeAgent ? (
        <p className="sr-only">{`Answering with ${activeAgent}`}</p>
      ) : null}
    </div>
  );
}

export default function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    void params
      .then(({ id }) => getConversation(id))
      .then((data) => {
        if (!cancelled) {
          setConversation(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [params]);

  if (loading) {
    return <ChatSkeleton />;
  }

  if (!conversation) {
    notFound();
    return null;
  }

  return <ConversationView conversation={conversation} />;
}