"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface ModuleTab {
  href: string;
  label: string;
  icon?: LucideIcon;
}

/**
 * Compact section-tab bar for CRM / ERP sub-navigation.
 *
 * Active state uses higher-contrast emerald instead of `text-primary`
 * because the ERP theme's primary (#86efac) is too light for readable text.
 */
export function ModuleTabs({ tabs }: { tabs: ModuleTab[] }) {
  const pathname = usePathname();

  const isActive = (tabHref: string) => {
    // Exact match
    if (pathname === tabHref) return true;

    // Prevent base/overview routes from matching all sub-routes
    if (tabHref.endsWith("/overview")) {
      return pathname === tabHref;
    }

    // Sub-route prefix match (e.g. /leads/123 matches /leads)
    return pathname.startsWith(tabHref);
  };

  return (
    <nav
      aria-label="Section navigation"
      className="flex items-center gap-1 overflow-x-auto border-b border-border/60"
      style={{ scrollbarWidth: "none" }}
    >
      {tabs.map((tab) => {
        const active = isActive(tab.href);
        const Icon = tab.icon;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative inline-flex h-9 shrink-0 items-center gap-1.5 px-3 text-sm font-medium transition-colors",
              active
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {Icon ? (
              <Icon
                aria-hidden="true"
                className={cn(
                  "size-4",
                  active
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-muted-foreground",
                )}
              />
            ) : null}
            {tab.label}
            {active && (
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-3 right-3 h-[2px] rounded-full bg-emerald-500 dark:bg-emerald-400"
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
