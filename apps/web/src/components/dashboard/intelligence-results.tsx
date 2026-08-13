"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowUpRight,
  BadgeCheck,
  Clock3,
  Sparkles,
  TrendingUp,
} from "lucide-react";

import type { SearchResponse } from "@/lib/mock/intelligence";
import { cn } from "@/lib/utils";

const SECTION_ICONS = {
  competitors: TrendingUp,
  "winning-products": BadgeCheck,
  niches: Sparkles,
  trends: TrendingUp,
} as const;

function confidenceLabel(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function ResultRow({
  title,
  source,
  snippet,
  confidence,
  timeframe,
}: {
  title: string;
  source: string;
  snippet: string;
  confidence: number;
  timeframe: string;
}) {
  return (
    <article className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30">
      <div className="flex items-start justify-between gap-4">
        <h3 className="font-display text-base font-semibold leading-snug text-foreground">
          {title}
        </h3>
        <span
          aria-hidden="true"
          className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:bg-primary/10 group-hover:text-primary"
        >
          <ArrowUpRight className="size-4" />
        </span>
      </div>
      <p className="mt-1 text-xs font-medium text-primary">{source}</p>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{snippet}</p>
      <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Clock3 aria-hidden="true" className="size-3.5" />
          {timeframe}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="text-emerald-600 dark:text-emerald-400">{confidenceLabel(confidence)}</span>
          confidence
        </span>
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
    return (
      <div className="space-y-4">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-border bg-card" />
        ))}
      </div>
    );
  }

  const generatedAt = new Date(response.generatedAt).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-border bg-card p-6">
        <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
          Summary
        </p>
        <h1 className="mt-1 font-display text-xl font-semibold tracking-tight text-foreground sm:text-2xl">
          {response.query}
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{response.summary}</p>
        <p className="mt-4 text-xs text-muted-foreground">
          Generated {generatedAt} · Sources across news, social, code, and trends
        </p>
      </section>

      {response.sections.map((section) => {
        const Icon = SECTION_ICONS[section.id] ?? Sparkles;
        return (
          <section key={section.id} className="space-y-3">
            <div className="flex items-center gap-2.5">
              <div className={cn("flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary")}>
                <Icon aria-hidden="true" className="size-4" />
              </div>
              <div>
                <h2 className="font-display text-base font-semibold tracking-tight text-foreground">
                  {section.label}
                </h2>
                <p className="text-xs text-muted-foreground">{section.description}</p>
              </div>
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
