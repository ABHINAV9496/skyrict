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
 * Active tab: green text + thin bottom indicator bar.
 * Inactive tabs: muted text, no background.
 */
export function ModuleTabs({ tabs }: { tabs: ModuleTab[] }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Section navigation"
      className="flex items-center gap-0.5 overflow-x-auto scrollbar-none"
    >
      {tabs.map((tab) => {
        const active =
          pathname === tab.href || pathname.startsWith(`${tab.href}/`);
        const Icon = tab.icon;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors",
              active
                ? "text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {Icon ? <Icon className="size-3.5" /> : null}
            {tab.label}
            {active ? (
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-2 right-2 h-[2px] rounded-full"
                style={{ backgroundColor: "var(--primary)" }}
              />
            ) : null}
          </Link>
        );
      })}
    </nav>
  );
}
