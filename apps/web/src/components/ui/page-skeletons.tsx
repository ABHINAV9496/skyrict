import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------------------
 * Shared primitives
 * ------------------------------------------------------------------------- */

/** A generic card-shaped block. */
export function CardSkeleton({ className }: { className?: string }) {
  return <Skeleton className={cn("h-36 rounded-2xl", className)} />;
}

/** A KPI / stat card (label, value, delta). */
export function StatCardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <Skeleton className="h-3 w-16 rounded-full" />
      <Skeleton className="mt-3 h-7 w-24" />
      <Skeleton className="mt-2 h-3 w-12 rounded-full" />
    </div>
  );
}

/** A table with a header row and body rows. */
export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex items-center gap-6 border-b border-border bg-muted/40 px-4 py-3">
        <Skeleton className="h-3 w-1/4 rounded-full" />
        <Skeleton className="h-3 w-1/3 rounded-full" />
        <Skeleton className="ml-auto h-3 w-16 rounded-full" />
      </div>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center gap-6 border-b border-border/60 px-4 py-3.5 last:border-0"
        >
          <Skeleton className="h-4 w-1/4" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="ml-auto h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

/** List rows with a leading square, two text lines, and a trailing pill. */
export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center gap-3 rounded-xl border border-border bg-card p-4"
        >
          <Skeleton className="size-9 shrink-0 rounded-lg" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3 w-2/5 rounded-full" />
            <Skeleton className="h-2.5 w-1/4 rounded-full" />
          </div>
          <Skeleton className="h-5 w-16 shrink-0 rounded-full" />
        </div>
      ))}
    </div>
  );
}

/** The page header block (icon tile + title + subtitle). */
export function PageHeaderSkeleton() {
  return (
    <div className="flex items-start gap-3">
      <Skeleton className="mt-0.5 size-10 shrink-0 rounded-xl" />
      <div className="space-y-2">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-3 w-72 rounded-full" />
      </div>
    </div>
  );
}

/** The workspace topbar (menu button, title, actions). */
export function TopbarSkeleton() {
  return (
    <div className="flex h-16 shrink-0 items-center justify-between gap-4 border-b border-border/70 bg-card/85 px-4 lg:px-6">
      <div className="flex min-w-0 items-center gap-2">
        <Skeleton className="size-9 rounded-lg lg:hidden" />
        <Skeleton className="h-5 w-40" />
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Skeleton className="size-9 rounded-lg" />
        <Skeleton className="size-9 rounded-lg" />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Workspace (main)
 * ------------------------------------------------------------------------- */

/** The workspace Overview: hero panel + Spaces heading + module pillar cards. */
export function OverviewSkeleton() {
  return (
    <div className="space-y-8">
      <div className="overflow-hidden rounded-2xl border border-border bg-card p-6 sm:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-center gap-4">
            <Skeleton className="size-12 shrink-0 rounded-xl" />
            <div className="space-y-2.5">
              <Skeleton className="h-6 w-48" />
              <div className="flex items-center gap-2">
                <Skeleton className="h-5 w-16 rounded-full" />
                <Skeleton className="h-5 w-24 rounded-full" />
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Skeleton className="h-9 w-24 rounded-lg" />
            <Skeleton className="h-9 w-20 rounded-lg" />
            <Skeleton className="size-9 rounded-lg" />
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Skeleton className="h-3 w-16 rounded-full" />
        <div aria-hidden="true" className="h-px flex-1 bg-border" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {[0, 1, 2].map((index) => (
          <div key={index} className="rounded-2xl border border-border bg-card p-6">
            <Skeleton className="size-12 rounded-2xl" />
            <Skeleton className="mt-5 h-5 w-2/3" />
            <Skeleton className="mt-2.5 h-3 w-full rounded-full" />
            <Skeleton className="mt-1.5 h-3 w-3/4 rounded-full" />
            <Skeleton className="mt-5 h-4 w-14" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** The workspace Settings page. */
export function SettingsSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeaderSkeleton />
      <div className="rounded-xl border border-border bg-card p-4">
        <Skeleton className="h-4 w-24" />
        <div className="mt-3 flex items-center gap-3">
          <Skeleton className="size-11 shrink-0 rounded-full" />
          <div className="space-y-1.5">
            <Skeleton className="h-3 w-32 rounded-full" />
            <Skeleton className="h-3 w-48 rounded-full" />
          </div>
        </div>
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </div>
      <div className="rounded-xl border border-border bg-card p-4">
        <Skeleton className="h-4 w-24" />
        <div className="mt-3 space-y-3">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
        </div>
      </div>
    </div>
  );
}

/** Members / Roles style page: header + list rows. */
export function ListPageSkeleton() {
  return (
    <div className="space-y-6">
      <PageHeaderSkeleton />
      <ListSkeleton rows={4} />
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * AI Agents world — chat application
 * ------------------------------------------------------------------------- */

/** The conversations rail (New chat, Recents, History, account footer). */
function AgentsRailSkeleton() {
  return (
    <aside className="hidden w-72 shrink-0 flex-col bg-background lg:flex lg:h-full lg:rounded-lg">
      <header className="flex items-center justify-between px-4 py-4">
        <Skeleton className="size-7 rounded-lg" />
        <Skeleton className="h-5 w-20" />
      </header>

      <div className="min-h-0 flex-1 space-y-6 overflow-hidden p-3">
        <Skeleton className="h-9 w-full rounded-lg" />

        <section className="space-y-1" aria-hidden="true">
          <Skeleton className="mb-2 ml-2.5 h-3 w-12 rounded-full" />
          <div className="flex h-8 items-center gap-3 rounded-lg px-2.5">
            <Skeleton className="h-3.5 w-1/2 rounded-md" />
          </div>
          <div className="flex h-8 items-center gap-3 rounded-lg px-2.5">
            <Skeleton className="h-3.5 w-1/3 rounded-md" />
          </div>
        </section>

        <section className="space-y-1" aria-hidden="true">
          <Skeleton className="mb-2 ml-2.5 h-3 w-14 rounded-full" />
          <div className="flex h-8 items-center gap-3 rounded-lg px-2.5">
            <Skeleton className="h-3.5 w-2/3 rounded-md" />
          </div>
          <div className="flex h-8 items-center gap-3 rounded-lg px-2.5">
            <Skeleton className="h-3.5 w-1/2 rounded-md" />
          </div>
        </section>
      </div>

      <div className="border-t border-sidebar-border p-3">
        <div className="flex h-8 items-center gap-3 rounded-lg px-2.5">
          <Skeleton className="size-[18px] rounded" />
          <Skeleton className="h-4 w-28" />
        </div>
      </div>

      <footer className="border-t border-sidebar-border p-3">
        <div className="flex items-center gap-3">
          <Skeleton className="size-8 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3 w-3/4 rounded-full" />
            <Skeleton className="h-2.5 w-1/2 rounded-full" />
          </div>
          <Skeleton className="size-8 shrink-0 rounded-lg" />
        </div>
      </footer>
    </aside>
  );
}

/** The AI Agents conversation view: header, message bubbles, composer. */
export function ChatSkeleton() {
  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <div className="flex h-12 shrink-0 items-center gap-2 px-4">
        <Skeleton className="size-8 rounded-lg" />
        <Skeleton className="h-4 w-44" />
      </div>
      <div className="flex-1 overflow-hidden px-4 py-6">
        <div className="mx-auto flex w-full max-w-[44rem] flex-col gap-6">
          <div className="flex justify-end">
            <Skeleton className="h-12 w-3/4 rounded-2xl rounded-br-md" />
          </div>
          <div className="flex justify-start gap-3">
            <Skeleton className="size-8 shrink-0 rounded-lg" />
            <Skeleton className="h-16 w-2/3 rounded-2xl rounded-bl-md" />
          </div>
          <div className="flex justify-end">
            <Skeleton className="h-10 w-1/2 rounded-2xl rounded-br-md" />
          </div>
          <div className="flex justify-start gap-3">
            <Skeleton className="size-8 shrink-0 rounded-lg" />
            <Skeleton className="h-20 w-3/4 rounded-2xl rounded-bl-md" />
          </div>
        </div>
      </div>
      <div className="shrink-0 px-4 pb-6 pt-2">
        <Skeleton className="h-24 w-full rounded-[1.5rem]" />
      </div>
    </div>
  );
}

/** The AI Agents home: hero, suggestion chips, composer. */
export function AgentsHomeSkeleton() {
  return (
    <div className="flex h-full flex-1 flex-col overflow-hidden">
      <div className="flex h-12 shrink-0 items-center gap-2 px-4">
        <Skeleton className="size-8 rounded-lg" />
        <Skeleton className="h-4 w-20" />
      </div>
      <div className="flex flex-1 flex-col overflow-hidden px-4 py-10">
        <div className="flex flex-1 flex-col items-center justify-center">
          <Skeleton className="size-12 rounded-2xl" />
          <Skeleton className="mt-5 h-7 w-72" />
          <Skeleton className="mt-3 h-3 w-96 max-w-full rounded-full" />
        </div>
        <div className="flex shrink-0 flex-col items-center gap-3">
          <Skeleton className="h-24 w-full max-w-[44rem] rounded-[1.5rem]" />
          <Skeleton className="h-3 w-48 rounded-full" />
          <Skeleton className="mt-2 h-9 w-64 rounded-full" />
        </div>
      </div>
    </div>
  );
}

/** Full-page AI Agents world: rail + chat area. */
export function AgentsWorldSkeleton() {
  return (
    <div className="flex h-dvh overflow-hidden bg-muted/30 p-2 theme-agents">
      <AgentsRailSkeleton />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg bg-sidebar">
        <ChatSkeleton />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * ERP world — conventional operations app
 * ------------------------------------------------------------------------- */

/** The ERP sidebar (brand, Operations nav, back link, account footer). */
function ErpSidebarSkeleton() {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-sidebar-border bg-sidebar lg:flex">
      <header className="flex items-center justify-between border-b border-sidebar-border px-4 py-4">
        <Skeleton className="h-7 w-24" />
        <Skeleton className="size-8 rounded-lg" />
      </header>

      <nav className="flex-1 space-y-6 overflow-hidden px-3 py-4" aria-hidden="true">
        <div className="space-y-1">
          <Skeleton className="mb-2 ml-3 h-3 w-20 rounded-full" />
          {Array.from({ length: 7 }).map((_, index) => (
            <div key={index} className="flex h-8 items-center gap-3 rounded-lg px-3">
              <Skeleton className="size-[18px] shrink-0 rounded" />
              <Skeleton className={index % 3 === 2 ? "h-4 w-16" : "h-4 w-24"} />
            </div>
          ))}
        </div>
      </nav>

      <div className="border-t border-sidebar-border p-3">
        <div className="flex h-8 items-center gap-3 rounded-lg px-3">
          <Skeleton className="size-[18px] shrink-0 rounded" />
          <Skeleton className="h-4 w-28" />
        </div>
      </div>

      <footer className="border-t border-sidebar-border p-3">
        <div className="flex items-center gap-3">
          <Skeleton className="size-8 shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <Skeleton className="h-3 w-3/4 rounded-full" />
            <Skeleton className="h-2.5 w-1/2 rounded-full" />
          </div>
          <Skeleton className="size-8 shrink-0 rounded-lg" />
        </div>
      </footer>
    </aside>
  );
}

/** ERP overview content: header + KPI cards + module cards grid. */
export function ErpOverviewSkeleton() {
  return (
    <div className="space-y-8">
      <PageHeaderSkeleton />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCardSkeleton />
        <StatCardSkeleton />
        <StatCardSkeleton />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((index) => (
          <CardSkeleton key={index} />
        ))}
      </div>
    </div>
  );
}

/** Full-page ERP world: sidebar + topbar + overview content. */
export function ErpWorldSkeleton() {
  return (
    <div className="flex h-dvh overflow-hidden bg-background theme-erp">
      <ErpSidebarSkeleton />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopbarSkeleton />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl px-4 py-6 lg:px-6 lg:py-8">
            <ErpOverviewSkeleton />
          </div>
        </main>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
 * Market Intelligence (Skyrict GMIE) world — search engine
 * ------------------------------------------------------------------------- */

/** The GMIE navbar (menu button, wordmark, routes, country, profile). */
export function IntelligenceNavSkeleton() {
  return (
    <header className="shrink-0 border-b border-border/70 bg-card/85">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-4 px-4 lg:px-6">
        <Skeleton className="size-10 shrink-0 rounded-lg" />
        <Skeleton className="h-6 w-32 shrink-0" />
        <div className="flex min-w-0 items-center gap-2 overflow-hidden">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-8 w-16 shrink-0 rounded-full" />
          ))}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Skeleton className="h-9 w-36 rounded-full" />
          <Skeleton className="size-9 rounded-full" />
        </div>
      </div>
    </header>
  );
}

/** The GMIE search landing: icon, title, hero search pill, suggestions. */
export function IntelligenceHomeSkeleton() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-8 text-center">
      <Skeleton className="size-14 rounded-2xl" />
      <div className="space-y-3">
        <Skeleton className="mx-auto h-8 w-64" />
        <Skeleton className="mx-auto h-3 w-96 max-w-full rounded-full" />
      </div>
      <div className="w-full max-w-2xl space-y-5">
        <Skeleton className="mx-auto h-14 w-full rounded-full" />
        <div className="flex flex-wrap items-center justify-center gap-2">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="h-8 w-52 rounded-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

/** A single market intelligence result card. */
export function ResultRowSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Skeleton className="h-5 w-24 rounded-full" />
          <Skeleton className="mt-2.5 h-5 w-3/4" />
        </div>
        <Skeleton className="size-7 shrink-0 rounded-lg" />
      </div>
      <Skeleton className="mt-3 h-3 w-full rounded-full" />
      <Skeleton className="mt-1.5 h-3 w-2/3 rounded-full" />
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-border/60 pt-3">
        <Skeleton className="h-3 w-20 rounded-full" />
        <div className="flex items-center gap-2">
          <Skeleton className="h-1.5 w-20 rounded-full" />
          <Skeleton className="h-3 w-8 rounded-full" />
        </div>
      </div>
    </div>
  );
}

/** The results summary card. */
export function SummarySkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-card p-6 sm:p-8">
      <div className="flex items-center gap-2">
        <Skeleton className="h-5 w-24 rounded-full" />
        <Skeleton className="h-3 w-20 rounded-full" />
      </div>
      <Skeleton className="mt-4 h-8 w-2/3" />
      <Skeleton className="mt-4 h-3 w-full rounded-full" />
      <Skeleton className="mt-1.5 h-3 w-4/5 rounded-full" />
      <div className="mt-6 flex flex-wrap items-center gap-2">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-6 w-28 rounded-full" />
        ))}
      </div>
    </div>
  );
}

/** Results list: summary + result cards. */
export function IntelligenceResultsListSkeleton() {
  return (
    <div className="space-y-8">
      <SummarySkeleton />
      <div className="space-y-3">
        {[0, 1, 2].map((index) => (
          <ResultRowSkeleton key={index} />
        ))}
      </div>
    </div>
  );
}

/** Full-page GMIE world: navbar + search landing. */
export function IntelligenceWorldSkeleton() {
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background">
      <IntelligenceNavSkeleton />
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl px-4 py-8 lg:px-6">
          <IntelligenceHomeSkeleton />
        </div>
      </main>
    </div>
  );
}
