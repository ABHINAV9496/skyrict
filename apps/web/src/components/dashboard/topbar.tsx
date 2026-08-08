"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const pageTitles: Record<string, string> = {
  "/dashboard": "Overview",
  "/dashboard/members": "Members",
  "/dashboard/agents": "AI Agents",
  "/dashboard/erp": "ERP",
  "/dashboard/intelligence": "Intelligence",
};

interface TopbarProps {
  onOpenMenu: () => void;
}

export function Topbar({ onOpenMenu }: TopbarProps) {
  const pathname = usePathname();
  const title = pageTitles[pathname] ?? "Dashboard";

  return (
    <header
      className={cn(
        "flex h-16 shrink-0 items-center justify-between gap-4 border-b border-border/70 bg-card/85 px-4 backdrop-blur-md lg:px-6",
      )}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onOpenMenu}
          aria-label="Open sidebar"
          className="flex size-9 items-center justify-center rounded-lg text-foreground transition-colors hover:bg-muted/60 lg:hidden"
        >
          <Menu aria-hidden="true" className="size-5" />
        </button>
        <h1 className="font-display text-lg font-semibold tracking-tight text-foreground">
          {title}
        </h1>
      </div>

      <Button asChild>
        <Link href="/dashboard/members">
          <UserPlus aria-hidden="true" />
          Invite member
        </Link>
      </Button>
    </header>
  );
}
