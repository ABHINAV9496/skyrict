"use client";

import { createContext, useContext, useState } from "react";

import { AgentsChatSidebar } from "@/components/dashboard/agents/agents-chat-sidebar";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import { useSession } from "@/lib/auth/session";

interface AgentsUIContextValue {
  collapsed: boolean;
  toggleCollapsed: () => void;
  openMobile: () => void;
  closeMobile: () => void;
}

const AgentsUIContext = createContext<AgentsUIContextValue | null>(null);

export function useAgentsUI(): AgentsUIContextValue {
  const value = useContext(AgentsUIContext);
  if (!value) {
    throw new Error("useAgentsUI must be used within AgentsShell");
  }
  return value;
}

/**
 * The AI Agents "world": a chat application. The left rail is conversation
 * navigation (New chat / Recents / History), the main column is the chat
 * itself — deliberately a different shape from the ERP and Intelligence worlds.
 * Mirrors the assistant-ui chat chrome: a muted stage around a rounded card.
 */
export function AgentsShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const { user } = useSession();

  return (
    <AgentsUIContext.Provider
      value={{
        collapsed,
        toggleCollapsed: () => setCollapsed((value) => !value),
        openMobile: () => setMobileOpen(true),
        closeMobile: () => setMobileOpen(false),
      }}
    >
      <ModuleAccessBoundary module="agents">
        <div className="flex h-dvh gap-2 overflow-hidden bg-muted/30 p-2 theme-agents">
          <AgentsChatSidebar
            collapsed={collapsed}
            mobileOpen={mobileOpen}
            onCloseMobile={() => setMobileOpen(false)}
          />
          <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg bg-sidebar">
            <main className="flex min-h-0 flex-1 flex-col">
              {children}
              <p className="sr-only">{`Signed in as ${user?.email ?? "you"}`}</p>
            </main>
          </div>
        </div>
      </ModuleAccessBoundary>
    </AgentsUIContext.Provider>
  );
}
