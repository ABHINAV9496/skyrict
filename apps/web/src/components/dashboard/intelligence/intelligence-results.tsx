"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowUpRight,
  BadgeCheck,
  ChartLine,
  Clock3,
  Database,
  Globe,
  Layers,
  MessageCircle,
  Newspaper,
  Play,
  Quote,
  Sparkles,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

import type { SearchResponse, SearchResult } from "@/lib/mock/intelligence";
import { IntelligenceResultsListSkeleton } from "@/components/ui/page-skeletons";
import { cn } from "@/lib/utils";

const SECTION_ICONS = {
  competitors: TrendingUp,
  "winning-products": BadgeCheck,
  niches: Sparkles,
  trends: ChartLine,
} as const;

interface SourceBadge {
  key: string;
  icon: LucideIcon;
  className: string;
}

const SOURCE_BADGES: { key: string; match: string; icon: LucideIcon; className: string }[] = [
  { key: "News", match: "News", icon: Newspaper, className: "bg-sky-500/10 text-sky-600 dark:text-sky-400" },
  { key: "Reddit", match: "Reddit", icon: MessageCircle, className: "bg-orange-500/10 text-orange-600 dark:text-orange-400" },
  { key: "YouTube", match: "YouTube", icon: Play, className: "bg-rose-500/10 text-rose-600 dark:text-rose-400" },
  { key: "GitHub", match: "GitHub", icon: Database, className: "bg-violet-500/10 text-violet-600 dark:text-violet-400" },
  { key: "Trends", match: "Trends", icon: TrendingUp, className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400" },
];

function sourceBadge(source: string): SourceBadge {
  const found = SOURCE_BADGES.find((badge) => source.includes(badge.match));
  if (found) return found;
  return { key: "Signal", icon: Globe, className: "bg-muted text-muted-foreground" };
}

function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2" title={`${pct}% confidence`}>
      <span aria-hidden="true" className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <span
          className="block h-full rounded-full bg-emerald-500 transition-[width] duration-700"
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="text-xs font-semibold text-emerald-600 tabular-nums dark:text-emerald-400">
        {pct}%
      </span>
    </div>
  );
}

function ResultRow({ title, source, snippet, confidence, timeframe }: SearchResult) {
  const badge = sourceBadge(source);
  const Icon = badge.icon;
  const detail = source.split(" · ")[1];

  return (
    <article className="group rounded-xl border border-border bg-card p-5 transition-all hover:border-primary/30 hover:shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
                badge.className,
              )}
            >
              <Icon aria-hidden="true" className="size-3" />
              {badge.key}
            </span>
            {detail ? <span className="text-xs text-muted-foreground">{detail}</span> : null}
          </div>
          <h3 className="mt-2 font-display text-base font-semibold leading-snug text-foreground">
            {title}
          </h3>
        </div>
        <span
          aria-hidden="true"
          className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary"
        >
          <ArrowUpRight className="size-4" />
        </span>
      </div>
      <p className="mt-2.5 text-sm leading-relaxed text-muted-foreground">{snippet}</p>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border/60 pt-3">
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock3 aria-hidden="true" className="size-3.5" />
          {timeframe}
        </span>
        <ConfidenceMeter value={confidence} />
      </div>
    </article>
  );
}

export function IntelligenceResults() {
  const searchParams = useSearchParams();
  const query = searchParams.get("q")?.trim() ?? "";
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!query) return;
    let cancelled = false;
    setResponse(null);
    setError(false);
    fetch(`/api/v1/intelligence/search?q=${encodeURIComponent(query)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error("failed"))))
      .then((body) => {
        if (!cancelled) setResponse(body.data as SearchResponse);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  const { signalCount, sourceKinds, avgConfidence } = useMemo(() => {
    if (!response) return { signalCount: 0, sourceKinds: [], avgConfidence: 0 };
    const results = response.sections.flatMap((section) => section.results);
    const sources = Array.from(new Set(results.map((result) => sourceBadge(result.source).key)));
    const average =
      results.reduce((sum, result) => sum + result.confidence, 0) / Math.max(results.length, 1);
    return { signalCount: results.length, sourceKinds: sources, avgConfidence: average };
  }, [response]);

  if (!query) {
    return (
      <p className="text-center text-sm text-muted-foreground">
        Enter a query above to start researching the market.
      </p>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-10 text-center">
        <AlertCircle aria-hidden="true" className="size-6 text-destructive" />
        <p className="text-sm text-muted-foreground">Couldn&apos;t run that search right now.</p>
      </div>
    );
  }

  if (!response) {
    return <IntelligenceResultsListSkeleton />;
  }

  const generatedAt = new Date(response.generatedAt).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-2xl border border-border bg-card p-6 sm:p-8">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-0 top-0 h-44 bg-gradient-to-b from-primary/10 to-transparent"
        />
        <div className="relative">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
              <Sparkles aria-hidden="true" className="size-3.5" />
              AI Research
            </span>
            <span className="text-xs text-muted-foreground">Generated {generatedAt}</span>
          </div>
          <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
            {response.query}
          </h1>
          <p className="mt-4 flex gap-3 text-sm leading-relaxed text-muted-foreground sm:text-base">
            <Quote aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-primary/60" />
            {response.summary}
          </p>
          <div className="mt-6 flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2.5 py-1 font-medium text-muted-foreground">
              <Layers aria-hidden="true" className="size-3.5" />
              {signalCount} signals
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2.5 py-1 font-medium text-muted-foreground">
              <ChartLine aria-hidden="true" className="size-3.5" />
              {response.sections.length} sections
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2.5 py-1 font-medium text-muted-foreground">
              <Globe aria-hidden="true" className="size-3.5" />
              {sourceKinds.join(" · ")}
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-emerald-500/10 px-2.5 py-1 font-medium text-emerald-600 dark:text-emerald-400">
              <TrendingUp aria-hidden="true" className="size-3.5" />
              {Math.round(avgConfidence * 100)}% avg. confidence
            </span>
          </div>
        </div>
      </section>

      {response.sections.map((section, index) => {
        const Icon = SECTION_ICONS[section.id] ?? Sparkles;
        return (
          <section key={section.id} className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon aria-hidden="true" className="size-[18px]" />
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <h2 className="font-display text-lg font-semibold tracking-tight text-foreground">
                      {section.label}
                    </h2>
                    <span
                      aria-hidden="true"
                      className="font-display text-sm font-bold text-muted-foreground/40"
                    >
                      {String(index + 1).padStart(2, "0")}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">{section.description}</p>
                </div>
              </div>
              <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                {section.results.length}
              </span>
            </div>
            <div className="space-y-3">
              {section.results.map((result) => (
                <ResultRow key={result.title} {...result} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
