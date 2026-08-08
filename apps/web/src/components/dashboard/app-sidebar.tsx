"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot,
  Boxes,
  Building2,
  LayoutDashboard,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  SlidersHorizontal,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

import { Logo } from "@/components/brand/logo";
import { useSession } from "@/lib/auth/session";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  soon?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
      { href: "/dashboard/members", label: "Members", icon: Users },
    ],
  },
  {
    label: "Modules",
    items: [
      { href: "/dashboard/agents", label: "AI Agents", icon: Bot },
      { href: "/dashboard/erp", label: "ERP", icon: Boxes },
      { href: "/dashboard/intelligence", label: "Intelligence", icon: Sparkles },
    ],
  },
  {
    label: "Manage",
    items: [
      { href: "/dashboard/settings", label: "Settings", icon: SlidersHorizontal, soon: true },
      { href: "/dashboard/integrations", label: "Integrations", icon: Plug, soon: true },
    ],
  },
];

function initialsFor(name: string, email: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length > 1) return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return email.slice(0, 2).toUpperCase() || "SK";
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/dashboard") return pathname === "/dashboard";
  return pathname === href || pathname.startsWith(`${href}/`);
}

interface AppSidebarProps {
  collapsed: boolean;
  mobileOpen: boolean;
  onToggleCollapsed: () => void;
  onCloseMobile: () => void;
}

export function AppSidebar({
  collapsed,
  mobileOpen,
  onToggleCollapsed,
  onCloseMobile,
}: AppSidebarProps) {
  const pathname = usePathname();
  const { user, logout } = useSession();

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
            collapsed ? "justify-center px-2" : "px-4",
          )}
        >
          <Link
            href="/dashboard"
            onClick={onCloseMobile}
            aria-label="Skyrict dashboard"
            className="text-sidebar-foreground"
          >
            <Logo wordmark={!collapsed} />
          </Link>
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
              {group.items.map((item) => {
                const active = isActive(pathname, item.href);
                const Icon = item.icon;
                if (item.soon) {
                  return (
                    <div
                      key={item.href}
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
                    key={item.href}
                    href={item.href}
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
              })}
            </div>
          ))}
        </nav>

        <div className="border-t border-sidebar-border p-3">
          <button
            type="button"
            onClick={onCloseMobile}
            title={collapsed ? "Business OS" : undefined}
            className={cn(
              "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground",
              collapsed && "justify-center px-0",
            )}
          >
            <Building2 aria-hidden="true" className="size-[18px] shrink-0" />
            {!collapsed ? <span className="truncate">Business OS</span> : null}
          </button>
        </div>

        <footer className="space-y-2 border-t border-sidebar-border p-3">
          <div
            className={cn(
              "flex items-center gap-3",
              collapsed && "flex-col justify-center",
            )}
          >
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary-foreground">
              {initialsFor(user?.fullName ?? "", user?.email ?? "")}
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
          <div className={cn("flex", collapsed ? "justify-center" : "justify-end")}>
            <button
              type="button"
              onClick={onToggleCollapsed}
              aria-expanded={!collapsed}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {collapsed ? (
                <PanelLeftOpen aria-hidden="true" className="size-4" />
              ) : (
                <PanelLeftClose aria-hidden="true" className="size-4" />
              )}
            </button>
          </div>
        </footer>
      </aside>
    </>
  );
}
