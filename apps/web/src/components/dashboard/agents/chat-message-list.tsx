"use client";

import { useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { AiGlyph } from "@/components/brand/logo";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/lib/mock/agents-store";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      aria-label="Copy message"
      title="Copy"
      className="flex size-7 shrink-0 items-center justify-center self-center rounded-lg text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:bg-muted hover:text-foreground"
    >
      {copied ? (
        <Check aria-hidden="true" className="size-3.5 text-emerald-500" />
      ) : (
        <Copy aria-hidden="true" className="size-3.5" />
      )}
    </button>
  );
}

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("group flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser ? (
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <AiGlyph aria-hidden="true" className="size-4" />
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
      {!isUser ? <CopyButton text={message.content} /> : null}
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
      <div className="flex flex-1 flex-col items-center justify-center px-4 text-center">
        <p className="text-sm text-muted-foreground">
          Start the conversation — ask anything about your business or the market.
        </p>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto px-4">
      <div className="mx-auto flex w-full max-w-[44rem] flex-col gap-6 py-4">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
      </div>
      <p className="sr-only">{`Chatting as ${userDisplay || "you"}`}</p>
    </div>
  );
}
