"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowLeft, LogOut, MessageSquareText, SquarePen } from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { getConversations } from "@/lib/api/agents-api";
import type { AuthUser } from "@/lib/api/auth-api";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/lib/mock/agents-store";

/** Same-origin avatar URL served by /api/auth/avatar/{user_id}/{filename}. */
function avatarSrc(user: AuthUser | null): string | null {
  return user?.avatarUrl ? `/api/auth/avatar/${user.avatarUrl}` : null;
}

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
  collapsed,
  onSelect,
}: {
  conversation: Conversation;
  active: boolean;
  collapsed: boolean;
  onSelect: () => void;
}) {
  return (
    <Link
      href={`/dashboard/agents/c/${conversation.id}`}
      onClick={onSelect}
      aria-current={active ? "page" : undefined}
      title={collapsed ? conversation.title : undefined}
      className={cn(
        "flex items-center gap-2 rounded-lg text-sm transition-colors",
        collapsed ? "justify-center px-0 py-2" : "px-2.5 py-2",
        active
          ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
      )}
    >
      {collapsed ? (
        <MessageSquareText aria-hidden="true" className="size-4 shrink-0" />
      ) : (
        <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
      )}
    </Link>
  );
}

function NewChatButton({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate: () => void;
}) {
  const router = useRouter();
  return (
    <Button
      variant="secondary"
      className={cn(
        "w-full gap-2 text-sidebar-foreground",
        collapsed ? "justify-center px-0" : "justify-start",
      )}
      title={collapsed ? "New chat" : undefined}
      onClick={() => {
        onNavigate();
        router.push("/dashboard/agents");
      }}
    >
      <SquarePen aria-hidden="true" className="size-4" />
      {!collapsed ? "New chat" : null}
    </Button>
  );
}

export function AgentsChatSidebar({
  mobileOpen,
  onCloseMobile,
  collapsed,
}: {
  mobileOpen: boolean;
  onCloseMobile: () => void;
  collapsed: boolean;
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
          "fixed inset-y-0 left-0 z-50 flex h-dvh flex-col bg-background transition-transform duration-300 ease-out lg:static lg:z-auto lg:h-full lg:translate-x-0 lg:rounded-lg",
          collapsed ? "w-16" : "w-72",
          "-translate-x-full",
          mobileOpen && "translate-x-0",
        )}
      >
        <header
          className={cn(
            "flex items-center border-b border-sidebar-border",
            collapsed ? "justify-center px-2 py-4" : "justify-between px-4 py-4",
          )}
        >
          <Link
            href="/dashboard/agents"
            onClick={onCloseMobile}
            aria-label="AI Agents home"
          >
            <Logo wordmark={false} tone="ai" />
          </Link>
          {!collapsed ? (
            <span className="font-display text-sm font-semibold tracking-tight text-sidebar-foreground">
              AI Agents
            </span>
          ) : null}
        </header>

        <div className="min-h-0 flex-1 space-y-6 overflow-y-auto p-3">
          <NewChatButton collapsed={collapsed} onNavigate={onCloseMobile} />

          <section className="space-y-1" aria-label="Recent conversations">
            {!collapsed ? (
              <p className="mb-2 px-2.5 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">
                Recents
              </p>
            ) : null}
            {conversations.length > 0 ? (
              conversations.map((conversation) => (
                <ConversationRow
                  key={conversation.id}
                  conversation={conversation}
                  active={isActive(pathname, conversation.id)}
                  collapsed={collapsed}
                  onSelect={onCloseMobile}
                />
              ))
            ) : (
              <p className="px-2.5 py-1.5 text-xs text-muted-foreground/70">
                No recent conversations yet.
              </p>
            )}
          </section>
        </div>

        <div className="border-t border-sidebar-border p-3">
          <Link
            href="/dashboard"
            onClick={onCloseMobile}
            data-tour="back-to-overview"
            title={collapsed ? "Back to overview" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-lg text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
              collapsed ? "justify-center px-0 py-2" : "px-2.5 py-2",
            )}
          >
            <ArrowLeft aria-hidden="true" className="size-[18px] shrink-0" />
            {!collapsed ? "Back to overview" : null}
          </Link>
        </div>

        <footer className="space-y-2 border-t border-sidebar-border p-3">
          <div className={cn("flex items-center gap-3", collapsed && "flex-col")}>
            <div className="flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/15 text-xs font-semibold text-primary-foreground">
              {avatarSrc(user) ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={avatarSrc(user) ?? ""}
                  alt={user?.fullName ? `${user.fullName}'s avatar` : "Profile avatar"}
                  className="size-full object-cover"
                />
              ) : (
                (user?.fullName || user?.email || "A").slice(0, 2).toUpperCase()
              )}
            </div>
            {!collapsed ? (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground">
                  {user?.fullName || user?.email || "Account"}
                </p>
                <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
              </div>
            ) : null}
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
