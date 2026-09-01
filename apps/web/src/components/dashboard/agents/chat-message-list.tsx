"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, Check, Copy, Pencil, RefreshCw, RotateCw } from "lucide-react";
import Markdown from "react-markdown";

import { AiGlyph } from "@/components/brand/logo";
import { cn } from "@/lib/utils";
import type { AgentChatMessage } from "@/lib/chat/use-agent-chat";

/* ------------------------------------------------------------------ */
/*  Utility helpers                                                    */
/* ------------------------------------------------------------------ */

/** Format an ISO timestamp to a short time like "6:23 PM". */
function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

/** Return a date-group label: "Today", "Yesterday", or "Aug 31, 2026". */
function dateGroupLabel(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diff = now.setHours(0, 0, 0, 0) - date.setHours(0, 0, 0, 0);
  const DAY = 86_400_000;
  if (diff < DAY) return "Today";
  if (diff < DAY * 2) return "Yesterday";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

/** True if two ISO timestamps fall on different calendar days. */
function differentDay(a: string, b: string): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return (
    da.getFullYear() !== db.getFullYear() ||
    da.getMonth() !== db.getMonth() ||
    da.getDate() !== db.getDate()
  );
}

/* ------------------------------------------------------------------ */
/*  Action buttons                                                     */
/* ------------------------------------------------------------------ */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    void navigator.clipboard?.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }, [text]);
  return (
    <button
      type="button"
      onClick={handleCopy}
      aria-label="Copy message"
      title="Copy"
      className="flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {copied ? (
        <Check aria-hidden="true" className="size-3.5 text-emerald-500" />
      ) : (
        <Copy aria-hidden="true" className="size-3.5" />
      )}
    </button>
  );
}

function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Edit message"
      title="Edit"
      className="flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <Pencil aria-hidden="true" className="size-3.5" />
    </button>
  );
}

function ResendButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Resend message"
      title="Resend"
      className="flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <RotateCw aria-hidden="true" className="size-3.5" />
    </button>
  );
}

function RetryButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Try again"
      title="Try again"
      className="flex size-7 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      <RefreshCw aria-hidden="true" className="size-3.5" />
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Citations                                                          */
/* ------------------------------------------------------------------ */

function AgentCitations({ message }: { message: AgentChatMessage }) {
  const citations = message.citations ?? [];
  if (citations.length === 0) return null;
  return (
    <div className="mt-3 space-y-1.5 border-t border-border/70 pt-2.5">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <BookOpen aria-hidden="true" className="size-3" />
        Sources
      </p>
      <ul className="space-y-1">
        {citations.map((citation, index) => (
          <li key={`${citation.sourceRef}-${index}`}>
            <a
              href={citation.url ?? citation.sourceRef}
              target={citation.url ? "_blank" : undefined}
              rel="noreferrer"
              className="text-xs text-primary underline-offset-2 hover:underline"
            >
              {citation.title}
              {citation.module ? (
                <span className="ml-1.5 text-muted-foreground">· {citation.module}</span>
              ) : null}
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Date separator                                                     */
/* ------------------------------------------------------------------ */

function DateSeparator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <div className="h-px flex-1 bg-border/60" />
      <span className="shrink-0 text-[11px] font-medium text-muted-foreground">{label}</span>
      <div className="h-px flex-1 bg-border/60" />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Message bubble                                                     */
/* ------------------------------------------------------------------ */

export const MessageBubble = memo(function MessageBubble({
  message,
  onResend,
}: {
  message: AgentChatMessage;
  onResend?: (content: string) => void;
}) {
  const isUser = message.role === "user";
  const streaming = !isUser && message.content === "" && message.failed !== true;
  const [editing, setEditing] = useState(false);

  return (
    <div className={cn("group flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser ? (
        <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <AiGlyph aria-hidden="true" className="size-4" />
        </div>
      ) : null}
      <div className={cn("relative flex max-w-[85%] flex-col sm:max-w-[75%]", isUser ? "items-end" : "items-start")}>
        <div
          className={cn(
            "whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-relaxed",
            isUser
              ? "bg-primary text-primary-foreground"
              : "border border-border bg-card text-foreground",
            message.failed ? "text-muted-foreground italic" : null,
          )}
        >
          {message.agentName && !isUser ? (
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {message.agentName}
            </p>
          ) : null}
          {streaming ? (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="size-1.5 animate-pulse rounded-full bg-primary" />
              <span className="size-1.5 animate-pulse rounded-full bg-primary delay-100" />
              <span className="size-1.5 animate-pulse rounded-full bg-primary delay-200" />
            </span>
          ) : isUser ? (
            message.content
          ) : (
            <div className="chat-markdown">
              <Markdown>{message.content}</Markdown>
            </div>
          )}
          {!isUser && message.content ? <AgentCitations message={message} /> : null}
        </div>

        {/* Action bar — visible on hover, positioned below without taking layout space */}
        {!streaming && message.content ? (
          <div
            className={cn(
              "absolute -bottom-7 flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100",
              isUser ? "right-0" : "left-11",
            )}
          >
            <CopyButton text={message.content} />
            {isUser ? (
              <>
                <EditButton onClick={() => setEditing(!editing)} />
                {onResend ? <ResendButton onClick={() => onResend(message.content)} /> : null}
              </>
            ) : message.failed ? (
              onResend ? <RetryButton onClick={() => onResend(message.content)} /> : null
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
});

/* ------------------------------------------------------------------ */
/*  Message list                                                       */
/* ------------------------------------------------------------------ */

export function MessageList({
  messages,
  userDisplay,
  onResend,
}: {
  messages: AgentChatMessage[];
  userDisplay: string;
  onResend?: (content: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const messageCountRef = useRef(messages.length);

  // Auto-scroll on new messages (not on content updates during streaming).
  useEffect(() => {
    if (messages.length > messageCountRef.current) {
      const node = scrollRef.current;
      if (node) node.scrollTop = node.scrollHeight;
    }
    messageCountRef.current = messages.length;
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
      <div className="mx-auto flex w-full max-w-[44rem] flex-col gap-3 pb-8 pt-4">
        {messages.map((message, index) => {
          const prev = index > 0 ? messages[index - 1] : null;
          const showDateSep = !prev || differentDay(prev.createdAt, message.createdAt);

          return (
            <div key={message.id}>
              {showDateSep ? (
                <DateSeparator label={dateGroupLabel(message.createdAt)} />
              ) : null}
              <MessageBubble message={message} onResend={onResend} />
            </div>
          );
        })}
      </div>
      <p className="sr-only">{`Chatting as ${userDisplay || "you"}`}</p>
    </div>
  );
}
