"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";

import { IntelligenceCountrySelect } from "@/components/dashboard/intelligence/intelligence-country-select";
import { IntelligenceMenu } from "@/components/dashboard/intelligence/intelligence-menu";
import { ModuleAccessBoundary } from "@/components/dashboard/shared/module-access-boundary";
import type { AuthUser } from "@/lib/api/auth-api";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

interface IntelligenceNavItem {
  href: string;
  label: string;
  exact?: boolean;
}

/**
 * Skyrict GMIE — the market intelligence "world". The top navbar carries the
 * wordmark, the module routes (Home, Explore, Trending, Market), a country
 * selector, and the profile. A menu button on the far left opens a drawer with
 * the utility routes (helpdesk, feedback, and more).
 */
const NAV_ITEMS: IntelligenceNavItem[] = [
  { href: "/dashboard/intelligence", label: "Home", exact: true },
  { href: "/dashboard/intelligence/explore", label: "Explore" },
  { href: "/dashboard/intelligence/trending", label: "Trending" },
  { href: "/dashboard/intelligence/market", label: "Market" },
];

/** The workspace surface strips the `/dashboard` prefix from public URLs. */
function normalizePath(pathname: string): string {
  return pathname.startsWith("/dashboard") ? pathname : `/dashboard${pathname}`;
}

function isActive(pathname: string, item: IntelligenceNavItem): boolean {
  const normalized = normalizePath(pathname);
  if (item.exact) return normalized === item.href;
  return normalized === item.href || normalized.startsWith(`${item.href}/`);
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

export function IntelligenceShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user } = useSession();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <ModuleAccessBoundary module="intelligence">
      <div className="flex h-dvh flex-col overflow-hidden bg-background">
        <header className="shrink-0 border-b border-border/70 bg-card/85 backdrop-blur-md">
          <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-4 px-4 lg:px-6">
            <button
              type="button"
              onClick={() => setMenuOpen(true)}
              aria-label="Open menu"
              aria-haspopup="dialog"
              aria-expanded={menuOpen}
              className="flex size-10 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60"
            >
              <Menu aria-hidden="true" className="size-5" />
            </button>

            <Link
              href="/dashboard/intelligence"
              className="shrink-0 pl-1"
              aria-label="Skyrict GMIE home"
            >
              <span className="font-display text-lg font-semibold tracking-tight text-foreground">
                Skyrict GMIE
              </span>
            </Link>

            <nav
              aria-label="Market intelligence"
              className="flex min-w-0 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              {NAV_ITEMS.map((item) => {
                const active = isActive(pathname, item);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "shrink-0 rounded-full px-3 py-1.5 text-sm font-medium transition-colors",
                      active
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                    )}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>

            <div className="ml-auto flex shrink-0 items-center gap-2">
              <IntelligenceCountrySelect />
              <Link
                href="/dashboard/settings"
                aria-label="Account"
                title="Account"
                className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/15 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/25"
              >
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
              </Link>
            </div>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-4 py-8 lg:px-6">{children}</div>
        </main>
      </div>

      <IntelligenceMenu open={menuOpen} onClose={() => setMenuOpen(false)} />
    </ModuleAccessBoundary>
  );
}
