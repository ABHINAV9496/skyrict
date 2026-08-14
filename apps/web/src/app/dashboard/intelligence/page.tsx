"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { IntelligenceBackground } from "@/components/dashboard/intelligence/intelligence-background";
import { IntelligenceSearch } from "@/components/dashboard/intelligence/intelligence-search";

const SUGGESTIONS = [
  "Most promising opportunities in AI infrastructure",
  "How competitors are pricing analytics tools",
  "Emerging trends in supply chain software",
  "What niche SaaS products are gaining traction",
];

function Suggestions() {
  const router = useRouter();

  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      {SUGGESTIONS.map((suggestion) => (
        <button
          key={suggestion}
          type="button"
          onClick={() => router.push(`/dashboard/intelligence/results?q=${encodeURIComponent(suggestion)}`)}
          className="rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-muted/40 hover:text-foreground"
        >
          {suggestion}
        </button>
      ))}
    </div>
  );
}

export default function IntelligencePage() {
  return (
    <div className="relative overflow-hidden">
      <IntelligenceBackground />
      <div className="relative flex min-h-[calc(100dvh-9rem)] flex-col items-center justify-center gap-8 text-center">
        <div>
          <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
            Search the market
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
            Real-time research across news, social, code, and trends — competitors,
            winning products, underserved niches, and what&apos;s shifting next.
          </p>
        </div>
        <div className="relative flex w-full flex-col items-center gap-5">
          <Suspense fallback={<div aria-hidden="true" className="h-12 w-full max-w-2xl rounded-full border border-border bg-muted/40" />}>
            <IntelligenceSearch variant="hero" />
          </Suspense>
          <Suggestions />
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            See the{" "}
            <Link
              href="/dashboard/intelligence/trending"
              className="font-display font-bold text-foreground underline underline-offset-4 transition-colors hover:text-primary"
            >
              trending now
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
