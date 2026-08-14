"use client";

import { useCallback, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import { Boxes, FilePen, FileText, Sparkles } from "lucide-react";

import { AgentsHeader } from "@/components/dashboard/agents/agents-header";
import { AiGlyph, LogoMark } from "@/components/brand/logo";
import { ChatComposer } from "@/components/dashboard/agents/chat-composer";
import { createConversation } from "@/lib/api/agents-api";
import { cn } from "@/lib/utils";

type SuggestionIcon = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean | "true" | "false";
}>;

const SUGGESTIONS: { icon: SuggestionIcon; title: string; prompt: string }[] = [
  {
    icon: Boxes,
    title: "Analyze",
    prompt: "Summarize what's happening in my business this week — sales, inventory, and cash flow.",
  },
  {
    icon: Sparkles,
    title: "Scan",
    prompt: "Find the biggest emerging opportunity in my market right now.",
  },
  {
    icon: AiGlyph,
    title: "Draft",
    prompt: "Draft an update for my team about this quarter's progress.",
  },
  {
    icon: FilePen,
    title: "Write",
    prompt: "Write a concise summary of my business performance this month.",
  },
  {
    icon: FileText,
    title: "Report",
    prompt: "Prepare a weekly operations report for my team.",
  },
];

export default function AgentsHomePage() {
  const router = useRouter();

  const startChat = useCallback(
    async (prompt: string) => {
      const conversation = await createConversation({ prompt });
      router.push(`/dashboard/agents/c/${conversation.id}`);
    },
    [router],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <AgentsHeader title="New Chat" />
      <div className="flex flex-1 flex-col items-center justify-center gap-6 overflow-y-auto px-4 py-8 -mt-6">
        <div className="flex flex-col items-center text-center">
          <LogoMark aria-hidden="true" className="size-12" tone="ai" />
          <h1 className="mt-5 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            How can I help you today?
          </h1>
        </div>

        <ChatComposer
          onSend={async (content) => {
            await startChat(content);
          }}
          placeholder="Ask your agent to analyze, scan, or draft…"
        />

        <div className="flex flex-wrap items-center justify-center gap-2">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion.title}
              type="button"
              onClick={() => void startChat(suggestion.prompt)}
              className={cn(
                "inline-flex h-auto items-center gap-1.5 rounded-full border border-border/60 px-3.5 py-1.5 text-sm font-normal text-foreground whitespace-nowrap transition-colors hover:bg-muted [&_svg]:size-4",
              )}
            >
              <suggestion.icon aria-hidden="true" className="text-primary" />
              {suggestion.title}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
