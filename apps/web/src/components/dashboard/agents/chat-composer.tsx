"use client";

import { useCallback, useRef, useState } from "react";
import { ArrowUp, LoaderCircle, Mic, Plus } from "lucide-react";

import { AiGlyph } from "@/components/brand/logo";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export function ChatComposer({
  onSend,
  placeholder = "Message Skyrict…",
}: {
  onSend: (content: string) => Promise<void>;
  placeholder?: string;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const [model, setModel] = useState("skyrict");
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
    <div className="mx-auto w-full max-w-[44rem]">
      <div className="flex flex-col rounded-[1.5rem] border border-border/60 bg-muted/30 p-2 shadow-sm transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/20 dark:border-muted-foreground/15 dark:focus-within:border-muted-foreground/30">
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
          className="max-h-40 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-sm text-foreground outline-none placeholder:text-muted-foreground/80"
        />
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Attach files"
              title="Attach files"
              className="flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              <Plus aria-hidden="true" className="size-4" />
            </button>
            <Select value={model} onValueChange={setModel}>
              <SelectTrigger
                size="sm"
                className="h-8 gap-1.5 rounded-full border-none bg-transparent px-2.5 text-xs font-medium text-muted-foreground shadow-none hover:bg-muted/70 data-[state=open]:bg-muted/70 [&_svg]:size-3.5"
              >
                <AiGlyph aria-hidden="true" className="size-3.5 text-primary" />
                <SelectValue placeholder="Model" />
              </SelectTrigger>
              <SelectContent align="start">
                <SelectItem value="skyrict">Skyrict Agent</SelectItem>
                <SelectItem value="skyrict-fast">Skyrict Fast</SelectItem>
                <SelectItem value="skyrict-pro">Skyrict Pro</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Voice input"
              title="Voice input"
              className="flex size-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              <Mic aria-hidden="true" className="size-4" />
            </button>
            <button
              type="button"
              onClick={() => void submit()}
              disabled={!value.trim() || sending}
              aria-label="Send message"
              className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground transition-opacity hover:bg-primary/80 disabled:opacity-40"
            >
              {sending ? (
                <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
              ) : (
                <ArrowUp aria-hidden="true" className="size-4" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
