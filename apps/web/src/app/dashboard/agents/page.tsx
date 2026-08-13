"use client";

import { useCallback, useMemo, type ComponentType } from "react";
import { useRouter } from "next/navigation";
import { Boxes, Sparkles } from "lucide-react";

import { AiGlyph, LogoMark } from "@/components/brand/logo";
import { ChatComposer } from "@/components/dashboard/agents/chat-composer";
import { createConversation } from "@/lib/api/agents-api";
import { useModuleAccess } from "@/lib/access/modules";
import { useSession } from "@/lib/auth/session";

type SuggestionIcon = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean | "true" | "false";
}>;

const SUGGESTIONS: { icon: SuggestionIcon; title: string; prompt: string }[] = [
  {
    icon: Boxes,
    title: "Analyze my business",
    prompt: "Summarize what's happening in my business this week — sales, inventory, and cash flow.",
  },
  {
    icon: Sparkles,
    title: "Scan the market",
    prompt: "Find the biggest emerging opportunity in my market right now.",
  },
  {
    icon: AiGlyph,
    title: "Draft something",
    prompt: "Draft an update for my team about this quarter's progress.",
  },
];

export default function AgentsHomePage() {
  const router = useRouter();
  const { user } = useSession();
  const { roles } = useModuleAccess();

  const firstName = useMemo(
    () => (user?.fullName ? user.fullName.trim().split(/\s+/)[0] : ""),
    [user],
  );

  const startChat = useCallback(
    async (prompt: string) => {
      const conversation = await createConversation({ prompt });
      router.push(`/dashboard/agents/c/${conversation.id}`);
    },
    [router],
  );

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-1 flex-col items-center justify-center px-4 py-10">
        <LogoMark aria-hidden="true" className="size-12" tone="ai" />
        <h1 className="mt-5 text-center font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          {firstName ? `Hi ${firstName}` : "Hi"} — what should I do next?
        </h1>
        <p className="mt-2 max-w-md text-center text-sm text-muted-foreground">
          Ask me to analyze your operations, scan the market, or draft something.
          I work inside your permissions and across your data.
        </p>

        <div className="mt-8 grid w-full max-w-2xl gap-3 sm:grid-cols-3">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion.title}
              type="button"
              onClick={() => void startChat(suggestion.prompt)}
              className="group flex flex-col items-start gap-2 rounded-xl border border-border bg-card p-4 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md hover:shadow-primary/5"
            >
              <suggestion.icon
                aria-hidden="true"
                className="size-4 text-primary transition-transform group-hover:scale-110"
              />
              <span className="text-sm font-medium text-foreground">{suggestion.title}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="shrink-0 px-4 pb-6">
        <ChatComposer
          onSend={async (content) => {
            await startChat(content);
          }}
          placeholder="Ask your agent to analyze, scan, or draft…"
        />
        {roles.length > 0 ? (
          <p className="mt-3 text-center text-xs text-muted-foreground">
            Acting with your role&apos;s permissions
          </p>
        ) : null}
      </div>
    </div>
  );
}
