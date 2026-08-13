"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, History, LogOut, SquarePen } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { getConversations } from "@/lib/api/agents-api";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/lib/mock/agents-store";

const RECENT_WINDOW_MS = 1000 * 60 * 60 * 48;

function isActive(pathname: string, id: string): boolean {
  const normalized =
    pathname === "/"
      ? "/dashboard"
      : pathname.startsWith("/dashboard")
        ? pathname
        : `/dashboard${pathname}`;
  return normalized === `/dashboard/agents/c/${id}`;
}

function ConversationRow({
  conversation,
  active,
  onSelect,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <Link
      href={`/dashboard/agents/c/${conversation.id}`}
      onClick={onSelect}
      aria-current={active ? "page" : undefined}
      title={conversation.title}
      className={cn(
        "group flex items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors",
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
      )}
    >
      <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
    </Link>
  );
}

function NewChatButton({ onNavigate }: { onNavigate: () => void }) {
  const router = useRouter();
  return (
    <Button
      variant="secondary"
      className="w-full justify-start gap-2 text-sidebar-foreground"
      onClick={() => {
        onNavigate();
        router.push("/dashboard/agents");
      }}
    >
      <SquarePen aria-hidden="true" className="size-4" />
      New chat
    </Button>
  );
}

export function AgentsChatSidebar({
  mobileOpen,
  onCloseMobile,
}: {
  mobileOpen: boolean;
  onCloseMobile: () => void;
}) {
  const pathname = usePathname();
  const { user, logout } = useSession();
  const [conversations, setConversations] = useState<Conversation[]>([]);

  const load = useCallback(() => {
    getConversations()
      .then(setConversations)
      .catch(() => setConversations([]));
  }, []);

  // Refresh when a conversation is created or the active one changes.
  useEffect(() => {
    load();
  }, [pathname, load]);

  const now = Date.now();
  const recents = conversations.filter(
    (conversation) => now - new Date(conversation.updatedAt).getTime() < RECENT_WINDOW_MS,
  );
  const history = conversations.filter(
    (conversation) => now - new Date(conversation.updatedAt).getTime() >= RECENT_WINDOW_MS,
  );

  return (
    <>
      {mobileOpen ? (
        <div
          aria-hidden="true"
          onClick={onCloseMobile}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex h-dvh w-72 flex-col border-r border-sidebar-border bg-sidebar",
          "-translate-x-full transition-transform duration-300 ease-out lg:static lg:z-auto lg:translate-x-0",
          mobileOpen && "translate-x-0",
        )}
      >
        <header className="flex items-center justify-between border-b border-sidebar-border px-4 py-4">
          <Link href="/dashboard/agents" onClick={onCloseMobile} aria-label="AI Agents home">
            <Logo wordmark={false} />
          </Link>
          <span className="font-display text-sm font-semibold tracking-tight text-sidebar-foreground">
            AI Agents
          </span>
        </header>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-3">
          <NewChatButton onNavigate={onCloseMobile} />

          <section className="space-y-1" aria-label="Recent conversations">
            <p className="mb-2 px-2.5 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">
              Recents
            </p>
            {recents.length > 0 ? (
              recents.map((conversation) => (
                <ConversationRow
                  key={conversation.id}
                  conversation={conversation}
                  active={isActive(pathname, conversation.id)}
                  onSelect={onCloseMobile}
                />
              ))
            ) : (
              <p className="px-2.5 py-1.5 text-xs text-muted-foreground/70">
                No recent conversations yet.
              </p>
            )}
          </section>

          <section className="space-y-1" aria-label="Conversation history">
            <p className="mb-2 flex items-center gap-1.5 px-2.5 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">
              <History aria-hidden="true" className="size-3" />
              History
            </p>
            {history.length > 0 ? (
              history.map((conversation) => (
                <ConversationRow
                  key={conversation.id}
                  conversation={conversation}
                  active={isActive(pathname, conversation.id)}
                  onSelect={onCloseMobile}
                />
              ))
            ) : (
              <p className="px-2.5 py-1.5 text-xs text-muted-foreground/70">
                Older conversations will appear here.
              </p>
            )}
          </section>
        </div>

        <div className="border-t border-sidebar-border p-3">
          <Link
            href="/dashboard"
            onClick={onCloseMobile}
            data-tour="back-to-overview"
            className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            <ArrowLeft aria-hidden="true" className="size-[18px] shrink-0" />
            Back to overview
          </Link>
        </div>

        <footer className="space-y-2 border-t border-sidebar-border p-3">
          <div className="flex items-center gap-3">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary-foreground">
              {(user?.fullName || user?.email || "A").slice(0, 2).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-foreground">
                {user?.fullName || user?.email || "Account"}
              </p>
              <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
            </div>
            <button
              type="button"
              onClick={() => void logout()}
              title="Sign out"
              aria-label="Sign out"
              className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <LogOut aria-hidden="true" className="size-4" />
            </button>
          </div>
        </footer>
      </aside>
    </>
  );
}
