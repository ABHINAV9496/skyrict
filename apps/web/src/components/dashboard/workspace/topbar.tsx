"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Inbox, Menu, Play } from "lucide-react";

import { cn } from "@/lib/utils";
import { resolvePageTitle } from "@/lib/page-title";
import { PAGE_TITLE_EVENT } from "@/lib/topbar-title";

interface TopbarProps {
  onOpenMenu: () => void;
}

export function Topbar({ onOpenMenu }: TopbarProps) {
  const pathname = usePathname();
  const [dynamicTitle, setDynamicTitle] = useState<string | null>(null);

  useEffect(() => {
    setDynamicTitle(null);
  }, [pathname]);

  useEffect(() => {
    function handleTitle(event: Event) {
      const { title } = (event as CustomEvent<{ title: string | null }>).detail ?? {};
      setDynamicTitle(typeof title === "string" && title.trim() ? title : null);
    }
    window.addEventListener(PAGE_TITLE_EVENT, handleTitle);
    return () => window.removeEventListener(PAGE_TITLE_EVENT, handleTitle);
  }, []);

  const baseTitle = resolvePageTitle(pathname);
  const title = dynamicTitle ? `${baseTitle} · ${dynamicTitle}` : baseTitle;

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
