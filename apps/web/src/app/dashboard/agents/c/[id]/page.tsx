"use client";

import { useCallback, useEffect, useState } from "react";
import { notFound } from "next/navigation";

import { AgentsHeader } from "@/components/dashboard/agents/agents-header";
import { ChatComposer } from "@/components/dashboard/agents/chat-composer";
import { MessageList } from "@/components/dashboard/agents/chat-message-list";
import { ChatSkeleton } from "@/components/ui/page-skeletons";
import { getConversation, sendMessage } from "@/lib/api/agents-api";
import { useSession } from "@/lib/auth/session";
import type { Conversation } from "@/lib/mock/agents-store";

export default function ConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { user } = useSession();
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

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

  const handleSend = useCallback(
    async (content: string) => {
      if (sending) return;
      setSending(true);
      try {
        const updated = await sendMessage(conversation!.id, content);
        setConversation(updated);
      } finally {
        setSending(false);
      }
    },
    [sending, conversation],
  );

  if (loading) {
    return <ChatSkeleton />;
  }

  if (!conversation) {
    notFound();
    return null;
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <AgentsHeader title={conversation.title} />
      <MessageList messages={conversation.messages} userDisplay={user?.fullName ?? user?.email ?? ""} />
      <div className="shrink-0 px-4 pb-4 pt-2 md:pb-6">
        <ChatComposer
          onSend={handleSend}
          placeholder="Continue the conversation…"
        />
      </div>
    </div>
  );
}
