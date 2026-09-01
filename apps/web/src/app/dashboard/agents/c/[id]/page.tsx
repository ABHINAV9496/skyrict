"use client";

import { useEffect, useRef, useState } from "react";
import { notFound } from "next/navigation";

import { AgentsHeader } from "@/components/dashboard/agents/agents-header";
import { ChatComposer } from "@/components/dashboard/agents/chat-composer";
import { MessageList } from "@/components/dashboard/agents/chat-message-list";
import { appendAgentMessage, getConversation, saveUserMessage } from "@/lib/api/agents-api";
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
  const { user, status } = useSession();
  const { messages, sending, activeAgent, send, stop } = useAgentChat(
    conversation.messages.map(toAgentMessage),
    {
      initialMessagesComplete: true,
      onUserMessage: (content) => {
        void saveUserMessage(conversation.id, content);
      },
      onComplete: (content) => {
        void appendAgentMessage(conversation.id, content);
      },
    },
  );
  const autoStarted = useRef(false);

  useEffect(() => {
    if (autoStarted.current || sending || status !== "authenticated") return;
    const last = conversation.messages[conversation.messages.length - 1];
    if (!last || last.role !== "user") return;
    // Echo the already-persisted last user message: append the agent bubble
    // and stream, but do not re-append or re-save the user message.
    //
    // Defer the actual send until after the current effect flush settles.
    // With reactStrictMode enabled, React (dev) simulates mount → unmount →
    // remount on the first commit; the synthetic unmount runs useAgentChat's
    // cleanup, which aborts any in-flight stream. If we called send() here
    // synchronously, that first auto-start stream would be cancelled before it
    // could produce a response — leaving only the persisted user message with
    // no assistant bubble. Deferring (and not setting autoStarted until the
    // timer actually fires) lets the strict double-invoke complete first so the
    // stream starts exactly once on the surviving mount and is never aborted.
    const id = window.setTimeout(() => {
      autoStarted.current = true;
      void send(last.content, true);
    }, 0);
    return () => window.clearTimeout(id);
  }, [conversation.messages, send, sending, status]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <AgentsHeader title={conversation.title} />
      <MessageList messages={messages} userDisplay={user?.fullName ?? user?.email ?? ""} onResend={send} />
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
    return (
      <div className="flex h-full flex-1 items-center justify-center">
        <div className="size-6 animate-spin rounded-full border-2 border-border border-t-primary" />
      </div>
    );
  }

  if (!conversation) {
    notFound();
    return null;
  }

  return <ConversationView conversation={conversation} />;
}