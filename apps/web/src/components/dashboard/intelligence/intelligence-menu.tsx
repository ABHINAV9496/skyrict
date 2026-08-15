"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BookOpen,
  CandlestickChart,
  CircleHelp,
  Compass,
  House,
  Keyboard,
  LogOut,
  MessageSquareText,
  ScanSearch,
  Sparkles,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";

import type { AuthUser } from "@/lib/api/auth-api";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

interface MenuItem {
  label: string;
  href?: string;
  icon: LucideIcon;
  soon?: boolean;
  exact?: boolean;
}

const MENU_GROUPS: { label: string; items: MenuItem[] }[] = [
  {
    label: "Browse",
    items: [
      { label: "Home", href: "/dashboard/intelligence", icon: House, exact: true },
      { label: "Explore", href: "/dashboard/intelligence/explore", icon: Compass },
      { label: "Trending", href: "/dashboard/intelligence/trending", icon: TrendingUp },
      { label: "Market", href: "/dashboard/intelligence/market", icon: CandlestickChart },
    ],
  },
  {
    label: "Support",
    items: [
      { label: "Helpdesk", href: "/dashboard/intelligence/helpdesk", icon: CircleHelp },
      { label: "Send feedback", href: "/dashboard/intelligence/feedback", icon: MessageSquareText },
    ],
  },
  {
    label: "Learn & more",
    items: [
      { label: "Documentation", icon: BookOpen, soon: true },
      { label: "Keyboard shortcuts", icon: Keyboard, soon: true },
      { label: "What's new", icon: Sparkles, soon: true },
    ],
  },
];

/** The workspace surface strips the `/dashboard` prefix from public URLs. */
function isActive(pathname: string, item: MenuItem): boolean {
  const normalized = pathname.startsWith("/dashboard")
    ? pathname
    : `/dashboard${pathname}`;
  const href = item.href ?? "";
  if (item.exact) return normalized === href;
  return normalized === href || normalized.startsWith(`${href}/`);
}

function initialsFor(name: string, email: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) {
    return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
  }
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase() || "SK";
}

/** Same-origin avatar URL served by /api/auth/avatar/{user_id}/{filename}. */
function avatarSrc(user: AuthUser | null): string | null {
  return user?.avatarUrl ? `/api/auth/avatar/${user.avatarUrl}` : null;
}

export function IntelligenceMenu({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();
  const lastPathname = useRef(pathname);
  const { user, logout } = useSession();

  useEffect(() => {
    // Close the drawer whenever the route changes (links also close it on
    // click; this covers any other navigation while it is open).
    if (lastPathname.current !== pathname) {
      lastPathname.current = pathname;
      onClose();
    }
  }, [pathname, onClose]);

  return (
    <>
      {open ? (
        <div
          aria-hidden="true"
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm"
        />
      ) : null}

      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex h-dvh w-80 max-w-[85vw] flex-col border-r border-border bg-card shadow-2xl transition-transform duration-300 ease-out",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
              <ScanSearch aria-hidden="true" className="size-4" />
            </div>
            <span className="font-display text-base font-semibold tracking-tight text-foreground">
              Skyrict GMIE
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close menu"
            className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        </header>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-5" aria-label="Menu">
          {MENU_GROUPS.map((group) => (
            <div key={group.label} className="space-y-1">
              <p className="mb-2 px-3 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">
                {group.label}
              </p>
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = item.href ? isActive(pathname, item) : false;
                if (item.soon) {
                  return (
                    <div
                      key={item.label}
                      aria-disabled="true"
                      className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground/60 select-none"
                    >
                      <Icon aria-hidden="true" className="size-[18px] shrink-0" />
                      <span className="truncate">{item.label}</span>
                      <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
                        Soon
                      </span>
                    </div>
                  );
                }
                return (
                  <Link
                    key={item.label}
                    href={item.href ?? "#"}
                    onClick={onClose}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                    )}
                  >
                    <Icon aria-hidden="true" className="size-[18px] shrink-0" />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <footer className="flex items-center gap-3 border-t border-border px-5 py-4">
          <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/15 text-xs font-semibold text-primary-foreground">
            {avatarSrc(user) ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={avatarSrc(user) ?? ""}
                alt={user?.fullName ? `${user.fullName}'s avatar` : "Profile avatar"}
                className="size-full object-cover"
              />
            ) : (
              initialsFor(user?.fullName ?? "", user?.email ?? "")
            )}
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
        </footer>
      </aside>
    </>
  );
}
