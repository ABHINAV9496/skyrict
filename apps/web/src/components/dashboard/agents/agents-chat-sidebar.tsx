"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowLeft,
  LogOut,
  MessageSquareText,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  SquarePen,
  Trash2,
} from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  deleteConversation,
  getConversations,
  renameConversation,
  setConversationPinned,
} from "@/lib/api/agents-api";
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
  onRename,
  onDelete,
  onTogglePin,
}: {
  conversation: Conversation;
  active: boolean;
  collapsed: boolean;
  onSelect: () => void;
  onRename: () => void;
  onDelete: () => void;
  onTogglePin: () => void;
}) {
  const pinned = Boolean(conversation.pinned);

  return (
    <div className={cn("group flex items-center rounded-lg", active ? "" : "hover:bg-muted/60")}>
      <Link
        href={`/dashboard/agents/c/${conversation.id}`}
        onClick={onSelect}
        aria-current={active ? "page" : undefined}
        title={collapsed ? conversation.title : undefined}
        className={cn(
          "flex min-w-0 flex-1 items-center gap-2 rounded-lg text-sm transition-colors",
          collapsed ? "justify-center px-0 py-2" : "px-2.5 py-2",
          active ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground" : "text-foreground",
        )}
      >
        {collapsed ? (
          <MessageSquareText aria-hidden="true" className="size-4 shrink-0" />
        ) : (
          <>
            <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
            {pinned ? (
              <Pin aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground/70" />
            ) : null}
          </>
        )}
      </Link>

      {!collapsed && (
        <div className="mr-1 flex shrink-0 items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 group-focus-within:opacity-100">
          {/* Quick pin/unpin action */}
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            tabIndex={-1}
            onClick={(event) => {
              event.preventDefault();
              onTogglePin();
            }}
            aria-label={pinned ? `Unpin ${conversation.title}` : `Pin ${conversation.title}`}
            title={pinned ? "Unpin chat" : "Pin chat"}
            className={cn("text-muted-foreground", pinned && "text-primary")}
          >
            {pinned ? (
              <PinOff aria-hidden="true" className="size-4" />
            ) : (
              <Pin aria-hidden="true" className="size-4" />
            )}
          </Button>

          {/* More actions: rename, delete, pin */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                tabIndex={-1}
                onClick={(event) => event.preventDefault()}
                aria-label={`Options for ${conversation.title}`}
                className="text-muted-foreground"
              >
                <MoreHorizontal aria-hidden="true" className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={onRename}>
                <Pencil aria-hidden="true" />
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={onTogglePin}>
                {pinned ? <PinOff aria-hidden="true" /> : <Pin aria-hidden="true" />}
                {pinned ? "Unpin chat" : "Pin chat"}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2 aria-hidden="true" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}
    </div>
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
  const router = useRouter();
  const { user, logout, status } = useSession();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const load = useCallback(() => {
    getConversations()
      .then(setConversations)
      .catch(() => setConversations([]));
  }, []);

  // Refresh when a conversation is created, the active one changes,
  // or the session hydrates (first load needs the token to exist).
  useEffect(() => {
    if (status === "authenticated") load();
  }, [pathname, load, status]);

  const handleRename = useCallback(
    (conversation: Conversation) => {
      setRenameTarget(conversation);
      setRenameValue(conversation.title);
    },
    [],
  );

  const submitRename = useCallback(() => {
    const target = renameTarget;
    const value = renameValue.trim();
    setRenameTarget(null);
    if (!target || !value || value === target.title) return;
    void renameConversation(target.id, value).then(() => load());
  }, [renameTarget, renameValue, load]);

  const handleDelete = useCallback(
    (conversation: Conversation) => {
      void deleteConversation(conversation.id).then(() => {
        // If the deleted conversation is the one we are viewing, leave the page.
        if (isActive(pathname, conversation.id)) {
          router.push("/dashboard/agents");
        }
        load();
      });
    },
    [pathname, router, load],
  );

  const handleTogglePin = useCallback(
    (conversation: Conversation) => {
      // Pinning re-sorts the list; optimistically update so the row moves
      // immediately, then reconcile with the server response.
      setConversations((previous) =>
        previous
          .map((item) =>
            item.id === conversation.id ? { ...item, pinned: !Boolean(item.pinned) } : item,
          )
          .sort(
            (a, b) =>
              Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) ||
              b.updatedAt.localeCompare(a.updatedAt),
          ),
      );
      void setConversationPinned(conversation.id, !conversation.pinned).then(() => load());
    },
    [load],
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
                  onRename={() => handleRename(conversation)}
                  onDelete={() => handleDelete(conversation)}
                  onTogglePin={() => handleTogglePin(conversation)}
                />
              ))
            ) : null}
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

      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(null);
        }}
      >
        <DialogContent
          className="sm:max-w-sm"
          onOpenAutoFocus={(event) => {
            // Focus the input so the user can start typing immediately.
            const input = document.querySelector<HTMLInputElement>(
              '[data-slot="rename-chat-input"]',
            );
            if (input) {
              event.preventDefault();
              input.focus();
            }
          }}
        >
          <DialogHeader>
            <DialogTitle>Rename chat</DialogTitle>
            <DialogDescription>
              Give this conversation a clearer name so it is easy to find later.
            </DialogDescription>
          </DialogHeader>
          <Input
            data-slot="rename-chat-input"
            value={renameValue}
            onChange={(event) => setRenameValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitRename();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setRenameTarget(null);
              }
            }}
            placeholder="Chat name"
            maxLength={60}
            aria-label="Chat name"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameTarget(null)}>
              Cancel
            </Button>
            <Button onClick={submitRename} disabled={!renameValue.trim()}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
