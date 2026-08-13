"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import { ScanSearch } from "lucide-react";

import { IntelligenceSearch } from "@/components/dashboard/intelligence-search";

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
          className="rounded-full border border-border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/40 hover:bg-muted/40 hover:text-foreground"
        >
          {suggestion}
        </button>
      ))}
    </div>
  );
}

export default function IntelligencePage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-8 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/15 text-primary">
        <ScanSearch aria-hidden="true" className="size-7" />
      </div>
      <div>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
          Search the market
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Real-time research across news, social, code, and trends — competitors,
          winning products, underserved niches, and what&apos;s shifting next.
        </p>
      </div>
      <div className="flex w-full flex-col items-center gap-5">
        <Suspense fallback={<div aria-hidden="true" className="h-12 w-full max-w-2xl rounded-full border border-border bg-muted/40" />}>
          <IntelligenceSearch variant="hero" />
        </Suspense>
        <Suggestions />
      </div>
    </div>
  );
}
