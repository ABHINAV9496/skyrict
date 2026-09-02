"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { AgentsHeader } from "@/components/dashboard/agents/agents-header";
import { ChatComposer } from "@/components/dashboard/agents/chat-composer";
import { MessageList } from "@/components/dashboard/agents/chat-message-list";
import { LogoMark } from "@/components/brand/logo";
import { appendAgentMessage, createConversation, saveUserMessage } from "@/lib/api/agents-api";
import type { ChatMessage, Conversation } from "@/lib/api/agents-api";
import { useSession } from "@/lib/auth/session";
import { useAgentChat, type AgentChatMessage } from "@/lib/chat/use-agent-chat";

function toAgentMessage(message: ChatMessage): AgentChatMessage {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    createdAt: message.created_at,
    agentName: message.agent_name ?? null,
    citations: [],
    failed: false,
  };
}

/** Live conversation view. Streams via SSE, no page navigation needed. */
function ConversationView({ conversation }: { conversation: Conversation }) {
  const { user, status } = useSession();
  const { messages, sending, activeAgent, send, stop } = useAgentChat(
    (conversation.messages ?? []).map(toAgentMessage),
    {
      initialMessagesComplete: true,
      conversationId: conversation.id,
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
    const msgs = conversation.messages ?? [];
    const last = msgs[msgs.length - 1];
    if (last && last.role === "user") {
      autoStarted.current = true;
      // Echo the already-persisted last user message: append the agent bubble
      // and stream, but do not re-append or re-save the user message.
      void send(last.content, true);
    }
  }, [conversation.messages, send, sending, status]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <AgentsHeader title={conversation.title} />
      <MessageList messages={messages} userDisplay={user?.fullName ?? user?.email ?? ""} onResend={send} />
      <div className="shrink-0 px-4 pb-4 pt-2 md:pb-6">
        <ChatComposer
          onSend={(content, attachments) => send(content, false, attachments)}
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

export default function AgentsHomePage() {
  const router = useRouter();
  const [conversation] = useState<Conversation | null>(null);

  const startChat = useCallback(async (prompt: string) => {
    const conv = await createConversation({ first_prompt: prompt });
    // Navigate to the conversation route so the sidebar picks it up from the
    // pathname change and the [id]/page.tsx takes over rendering.
    router.push(`/dashboard/agents/c/${conv.id}`);
  }, [router]);

  if (conversation) {
    return <ConversationView conversation={conversation} />;
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <AgentsHeader title="New Chat" />
      <div className="flex flex-1 flex-col items-center justify-center gap-6 overflow-y-auto px-4 py-8 -mt-6">
        <div className="flex flex-col items-center text-center">
          <LogoMark aria-hidden="true" className="size-12" tone="ai" />
          <h1 className="mt-5 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            How can I help you today?
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Ask about your business, market trends, or any task.
          </p>
        </div>

        <ChatComposer
          onSend={startChat}
          placeholder="Ask your agent anything…"
        />
      </div>
    </div>
  );
}
