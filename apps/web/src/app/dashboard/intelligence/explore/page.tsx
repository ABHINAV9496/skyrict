"use client";

import { useRouter } from "next/navigation";
import {
  BadgeCheck,
  Compass,
  Globe,
  Sparkles,
  Tags,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";

interface ExploreCategory {
  title: string;
  description: string;
  query: string;
  icon: LucideIcon;
}

const CATEGORIES: ExploreCategory[] = [
  {
    title: "Competitor landscapes",
    description: "Map who is moving in a space, their pricing, and traction.",
    query: "competitive landscape for analytics tools",
    icon: TrendingUp,
  },
  {
    title: "Winning products",
    description: "Products gaining share — and why buyers pick them.",
    query: "winning products in AI infrastructure",
    icon: BadgeCheck,
  },
  {
    title: "Underserved niches",
    description: "Crowded ideas with empty shelves. Whitespace worth building.",
    query: "underserved niches in SaaS",
    icon: Sparkles,
  },
  {
    title: "Pricing intelligence",
    description: "How competitors price, bundle, and discount their offers.",
    query: "pricing strategies for B2B software",
    icon: Tags,
  },
  {
    title: "Regional markets",
    description: "Demand clusters and growth by geography.",
    query: "market opportunities in Southeast Asia",
    icon: Globe,
  },
  {
    title: "Trending signals",
    description: "What is shifting across news, social, code, and trends.",
    query: "emerging trends in supply chain software",
    icon: Compass,
  },
];

export default function ExplorePage() {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-4xl">
      <header className="text-center">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Explore the market
        </h1>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
          Pick a lens and Skyrict GMIE will run a fresh research pass across
          news, social, code, and trends.
        </p>
      </header>

      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        {CATEGORIES.map((category) => {
          const Icon = category.icon;
          return (
            <button
              key={category.title}
              type="button"
              onClick={() =>
                router.push(
                  `/dashboard/intelligence/results?q=${encodeURIComponent(category.query)}`,
                )
              }
              className="group flex items-start gap-4 rounded-2xl border border-border bg-card p-5 text-left transition-colors hover:border-primary/40"
            >
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon aria-hidden="true" className="size-5" />
              </div>
              <div>
                <h2 className="font-display text-base font-semibold tracking-tight text-foreground">
                  {category.title}
                </h2>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {category.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
