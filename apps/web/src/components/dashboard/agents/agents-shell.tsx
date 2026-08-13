"use client";

import { useState } from "react";
import { Menu } from "lucide-react";

import { AgentsChatSidebar } from "@/components/dashboard/agents/agents-chat-sidebar";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { useSession } from "@/lib/auth/session";

/**
 * The AI Agents "world": a chat application. The left rail is conversation
 * navigation (New chat / Recents / History), the main column is the chat
 * itself — deliberately a different shape from the ERP and Intelligence worlds.
 */
export function AgentsShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user } = useSession();

  return (
    <ModuleAccessBoundary module="agents">
      <div className="flex h-dvh overflow-hidden bg-background theme-agents">
        <AgentsChatSidebar mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border/70 bg-card/85 px-4 backdrop-blur-md lg:hidden">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              aria-label="Open chats"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60"
            >
              <Menu aria-hidden="true" className="size-5" />
            </button>
            <p className="font-display text-sm font-semibold tracking-tight text-foreground">
              AI Agents
            </p>
          </header>
          <main className="flex min-h-0 flex-1 flex-col">
            {children}
            <p className="sr-only">{`Signed in as ${user?.email ?? "you"}`}</p>
          </main>
        </div>
      </div>
    </ModuleAccessBoundary>
  );
}
