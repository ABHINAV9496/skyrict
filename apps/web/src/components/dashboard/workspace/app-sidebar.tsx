"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  Blocks,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";

import { Logo, type LogoMarkTone } from "@/components/brand/logo";
import type { NavGroup, NavItem } from "@/components/dashboard/workspace/sidebar-config";
import { UserMenu } from "@/components/dashboard/workspace/user-menu";
import { cn } from "@/lib/utils";

/**
 * Compare the active path against an internal `/dashboard/*` href. The public
 * workspace URL strips the prefix (e.g. `/settings`), so normalize it before
 * comparing so the active state tracks the page regardless of which form the
 * browser is showing.
 */
function isActive(pathname: string, item: NavItem): boolean {
  const normalized =
    pathname === "/"
      ? "/dashboard"
      : pathname.startsWith("/dashboard")
        ? pathname
        : `/dashboard${pathname}`;
  const { href, exact } = item;
  if (href === "/dashboard" || exact) return normalized === href;
  return normalized === href || normalized.startsWith(`${href}/`);
}

function SidebarLink({
  item,
  collapsed,
  pathname,
  onCloseMobile,
}: {
  item: NavItem;
  collapsed: boolean;
  pathname: string;
  onCloseMobile: () => void;
}) {
  const active = isActive(pathname, item);
  const Icon = item.icon;

  if (item.soon) {
    return (
      <div
        data-tour={item.tour}
        title={collapsed ? item.label : undefined}
        aria-disabled="true"
        className={cn(
          "flex items-center gap-3 rounded-lg text-sm font-medium text-muted-foreground/60 select-none",
          collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
        )}
      >
        <Icon aria-hidden="true" className="size-[18px] shrink-0" />
        {!collapsed ? (
          <>
            <span className="truncate">{item.label}</span>
            <span className="ml-auto rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
              Soon
            </span>
          </>
        ) : null}
      </div>
    );
  }

  return (
    <Link
      href={item.href}
      data-tour={item.tour}
      onClick={onCloseMobile}
      title={collapsed ? item.label : undefined}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-lg text-sm font-medium transition-colors",
        collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
      )}
    >
      {active ? (
        <span
          aria-hidden="true"
          className="absolute top-1/2 left-0 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary"
        />
      ) : null}
      <Icon
        aria-hidden="true"
        className={cn("size-[18px] shrink-0", active && "text-primary")}
      />
      {!collapsed ? <span className="truncate">{item.label}</span> : null}
    </Link>
  );
}

export interface AppSidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapsed: () => void;
  onCloseMobile: () => void;
  navGroups: NavGroup[];
  accountItems: NavItem[];
  /** Root the sidebar logo lands on (workspace overview vs. a module home). */
  brandHref?: string;
  /** Tints the logo mark for module worlds (ERP renders a green mark). */
  logoTone?: LogoMarkTone;
  /** Module sidebars render a "Back to overview" link above the footer. */
  showBackToOverview?: boolean;
}

export function AppSidebar({
  collapsed,
  mobileOpen,
  onToggleCollapsed,
  onCloseMobile,
  navGroups,
  accountItems,
  brandHref = "/dashboard",
  logoTone = "sky",
  showBackToOverview = false,
}: AppSidebarProps) {
  const pathname = usePathname();

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
          "fixed inset-y-0 left-0 z-50 flex h-dvh flex-col border-r border-sidebar-border bg-sidebar transition-[width,transform] duration-300 ease-out",
          collapsed ? "w-[4.5rem]" : "w-64",
          "-translate-x-full lg:static lg:z-auto lg:translate-x-0",
          mobileOpen && "translate-x-0",
        )}
      >
        <header
          className={cn(
            "flex items-center border-b border-sidebar-border py-4",
            collapsed ? "justify-center px-2" : "justify-between px-4",
          )}
        >
          <Link
            href={brandHref}
            onClick={onCloseMobile}
            aria-label="Skyrict dashboard"
            className={cn("text-sidebar-foreground", collapsed && "hidden")}
          >
            {logoTone === "erp" ? (
              <span className="inline-flex items-center gap-2.5">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-300 to-emerald-400 text-emerald-950">
                  <Blocks aria-hidden="true" className="size-4" />
                </span>
                {!collapsed ? (
                  <span className="font-display text-lg font-semibold tracking-tight">
                    Skyrict
                  </span>
                ) : null}
              </span>
            ) : (
              <Logo wordmark={!collapsed} tone={logoTone} />
            )}
          </Link>
          <button
            type="button"
            onClick={onToggleCollapsed}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            {collapsed ? (
              <PanelLeftOpen aria-hidden="true" className="size-4" />
            ) : (
              <PanelLeftClose aria-hidden="true" className="size-4" />
            )}
          </button>
        </header>

        <nav className="flex-1 space-y-6 overflow-y-auto px-3 py-4" aria-label="Dashboard">
          {navGroups.map((group) => (
            <div key={group.label} className="space-y-1">
              {collapsed ? (
                <div className="mx-1 mb-2 h-px bg-sidebar-border" aria-hidden="true" />
              ) : (
                <p className="mb-2 px-3 text-[11px] font-semibold tracking-wider text-muted-foreground/80 uppercase">
                  {group.label}
                </p>
              )}
              {group.items.map((item) => (
                <SidebarLink
                  key={item.href}
                  item={item}
                  collapsed={collapsed}
                  pathname={pathname}
                  onCloseMobile={onCloseMobile}
                />
              ))}
            </div>
          ))}
        </nav>

        {showBackToOverview ? (
          <div className="border-t border-sidebar-border p-3">
            <Link
              href="/dashboard"
              onClick={onCloseMobile}
              data-tour="back-to-overview"
              title={collapsed ? "Back to overview" : undefined}
              className={cn(
                "group flex items-center gap-3 rounded-lg text-sm font-medium transition-colors",
                collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
                "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              <ArrowLeft
                aria-hidden="true"
                className="size-[18px] shrink-0 transition-transform group-hover:-translate-x-0.5"
              />
              {!collapsed ? <span className="truncate">Back to overview</span> : null}
            </Link>
          </div>
        ) : null}

        {accountItems.length > 0 ? (
          <div className="space-y-1 border-t border-sidebar-border p-3">
            {accountItems.map((item) => (
              <SidebarLink
                key={item.href}
                item={item}
                collapsed={collapsed}
                pathname={pathname}
                onCloseMobile={onCloseMobile}
              />
            ))}
          </div>
        ) : null}

        <footer
          data-tour="sidebar-profile"
          className="border-t border-sidebar-border p-3"
        >
          <UserMenu collapsed={collapsed} />
        </footer>
      </aside>
    </>
  );
}
