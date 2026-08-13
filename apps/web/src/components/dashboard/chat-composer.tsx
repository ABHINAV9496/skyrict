"use client";

import { useCallback, useRef, useState } from "react";
import { ArrowUp, LoaderCircle } from "lucide-react";

export function ChatComposer({
  onSend,
  placeholder = "Message Skyrict…",
}: {
  onSend: (content: string) => Promise<void>;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = useCallback(async () => {
    const content = value.trim();
    if (!content || sending) return;
    setSending(true);
    setValue("");
    try {
      await onSend(content);
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  }, [value, sending, onSend]);

  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-sm focus-within:border-primary/40 focus-within:ring-3 focus-within:ring-ring/20">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          rows={1}
          placeholder={placeholder}
          aria-label="Message"
          className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-foreground outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!value.trim() || sending}
          aria-label="Send message"
          className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-opacity disabled:opacity-40"
        >
          {sending ? (
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
          ) : (
            <ArrowUp aria-hidden="true" className="size-4" />
          )}
        </button>
      </div>
    </div>
  );
}
