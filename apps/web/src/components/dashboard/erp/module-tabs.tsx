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
 * Horizontal section tabs for ERP modules (e.g. Leads / Opportunities /
 * Customers under CRM). Mirrors the sidebar's active-state styling.
 */
export function ModuleTabs({ tabs }: { tabs: ModuleTab[] }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Section navigation"
      className="flex items-center gap-1 overflow-x-auto rounded-xl border border-border bg-card p-1"
    >
      {tabs.map((tab) => {
        const active = pathname === tab.href || pathname.startsWith(`${tab.href}/`);
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {tab.icon ? <tab.icon aria-hidden="true" className="size-4" /> : null}
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
