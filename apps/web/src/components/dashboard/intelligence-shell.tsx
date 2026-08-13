"use client";

import { Suspense } from "react";
import Link from "next/link";
import { ArrowLeft, ScanSearch } from "lucide-react";

import { IntelligenceSearch } from "@/components/dashboard/intelligence-search";
import { ModuleAccessBoundary } from "@/components/dashboard/module-access-boundary";

/**
 * The Intelligence "world": a market search engine. There is no sidebar — the
 * navbar carries the wordmark, a back-link to the workspace, and the persistent
 * search bar, so searching feels like a destination rather than a page.
 */
export function IntelligenceShell({ children }: { children: React.ReactNode }) {
  return (
    <ModuleAccessBoundary module="intelligence">
      <div className="flex h-dvh flex-col overflow-hidden bg-background theme-intelligence">
        <header className="shrink-0 border-b border-border/70 bg-card/85 backdrop-blur-md">
          <div className="mx-auto flex h-14 w-full max-w-5xl items-center gap-3 px-4 lg:px-6">
            <Link
              href="/dashboard"
              aria-label="Back to Overview"
              className="flex size-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <ArrowLeft aria-hidden="true" className="size-4" />
            </Link>
            <Link href="/dashboard/intelligence" className="flex shrink-0 items-center gap-2">
              <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <ScanSearch aria-hidden="true" className="size-4" />
              </div>
              <span className="font-display text-sm font-semibold tracking-tight text-foreground">
                Market Intelligence
              </span>
            </Link>
            <div className="min-w-0 flex-1">
              <Suspense fallback={<div aria-hidden="true" className="h-9 w-full max-w-xl rounded-full border border-border bg-muted/40" />}>
                <IntelligenceSearch variant="navbar" />
              </Suspense>
            </div>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-4 py-8 lg:px-6">{children}</div>
        </main>
      </div>
    </ModuleAccessBoundary>
  );
}
