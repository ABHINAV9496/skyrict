"use client";

import { useCallback, useEffect, useState } from "react";
import { notFound } from "next/navigation";
import { LoaderCircle } from "lucide-react";

import { ChatComposer } from "@/components/dashboard/chat-composer";
import { MessageList } from "@/components/dashboard/chat-message-list";
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
    return (
      <div className="flex flex-1 items-center justify-center">
        <LoaderCircle aria-hidden="true" className="size-5 animate-spin text-primary" />
      </div>
    );
  }

  if (!conversation) {
    notFound();
    return null;
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="shrink-0 border-b border-border/70 px-4 py-3 lg:px-6">
        <h1 className="truncate font-display text-sm font-semibold tracking-tight text-foreground">
          {conversation.title}
        </h1>
      </header>
      <MessageList messages={conversation.messages} userDisplay={user?.fullName ?? user?.email ?? ""} />
      <div className="shrink-0 px-4 pb-6 pt-2">
        <ChatComposer
          onSend={handleSend}
          placeholder="Continue the conversation…"
        />
      </div>
    </div>
  );
}
