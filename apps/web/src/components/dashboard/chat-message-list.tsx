"use client";

import { useEffect, useRef } from "react";
import { Bot } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/mock/agents-store";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser ? (
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <Bot aria-hidden="true" className="size-4" />
        </div>
      ) : null}
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed sm:max-w-[75%]",
          isUser
            ? "bg-primary text-primary-foreground"
            : "border border-border bg-card text-foreground",
        )}
      >
        {message.content}
      </div>
    </div>
  );
}

export function MessageList({
  messages,
  userDisplay,
}: {
  messages: ChatMessage[];
  userDisplay: string;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-center">
        <p className="text-sm text-muted-foreground">
          Start the conversation — ask anything about your business or the market.
        </p>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto py-4">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}
      <p className="sr-only">{`Chatting as ${userDisplay || "you"}`}</p>
    </div>
  );
}
