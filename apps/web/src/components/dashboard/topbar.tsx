"use client";

import { usePathname } from "next/navigation";
import { Inbox, Menu, Play } from "lucide-react";

import { cn } from "@/lib/utils";

const knownTitles: Record<string, string> = {
  "/dashboard": "Overview",
  "/dashboard/members": "Members",
  "/dashboard/agents": "AI Agents",
  "/dashboard/erp": "ERP",
  "/dashboard/intelligence": "Intelligence",
  "/dashboard/settings": "Settings",
  "/dashboard/integrations": "Integrations",
};

const idPattern = /^(?:\d+|[\da-f]{8,})$/i;

function humanize(segment: string): string {
  return segment
    .replace(/[-_]+/g, " ")
    .replace(/([a-z\d])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

/** Resolve a page title from any workspace route, known or not. */
function resolvePageTitle(pathname: string): string {
  const normalized =
    pathname === "/"
      ? "/dashboard"
      : pathname.startsWith("/dashboard")
        ? pathname
        : `/dashboard${pathname}`;
  if (knownTitles[normalized]) return knownTitles[normalized];

  const segments = normalized.split("/").filter(Boolean);
  const parent = Object.keys(knownTitles)
    .filter((key) => normalized.startsWith(`${key}/`))
    .sort((a, b) => b.length - a.length)[0];

  const rest = parent
    ? segments
        .slice(parent.split("/").filter(Boolean).length)
        .filter((segment) => !idPattern.test(segment))
        .map(humanize)
    : [];

  if (parent && rest.length > 0) return `${knownTitles[parent]} · ${rest.join(" · ")}`;

  const last = [...segments].reverse().find((segment) => !idPattern.test(segment));
  return last ? humanize(last) : "Dashboard";
}

interface TopbarProps {
  onOpenMenu: () => void;
}

export function Topbar({ onOpenMenu }: TopbarProps) {
  const pathname = usePathname();
  const title = resolvePageTitle(pathname);

  return (
    <header
      className={cn(
        "flex h-16 shrink-0 items-center justify-between gap-4 border-b border-border/70 bg-card/85 px-4 backdrop-blur-md lg:px-6",
      )}
    >
      <div className="flex min-w-0 items-center gap-2">
        <button
          type="button"
          onClick={onOpenMenu}
          aria-label="Open sidebar"
          className="flex size-9 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60 lg:hidden"
        >
          <Menu aria-hidden="true" className="size-5" />
        </button>
        <h1 className="truncate font-display text-lg font-semibold tracking-tight text-foreground">
          {title}
        </h1>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        {(pathname === "/" || pathname === "/dashboard") && (
          <button
            type="button"
            aria-label="Replay product tour"
            title="Replay tour"
            onClick={() => window.dispatchEvent(new Event("skyrict:start-tour"))}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60"
          >
            <Play aria-hidden="true" className="size-5" />
          </button>
        )}
        <button
          type="button"
          aria-label="Inbox"
          title="Inbox"
          className="flex size-9 shrink-0 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60"
        >
          <Inbox aria-hidden="true" className="size-5" />
        </button>
      </div>
    </header>
  );
}
