"use client";

import { useRouter } from "next/navigation";
import { ArrowUpRight, Flame } from "lucide-react";

interface TrendingTopic {
  rank: number;
  term: string;
  category: string;
  region: string;
  momentum: string;
  note: string;
}

const TRENDING: TrendingTopic[] = [
  {
    rank: 1,
    term: "Agentic AI tools",
    category: "AI & Infrastructure",
    region: "Global",
    momentum: "+128%",
    note: "Developer adoption accelerating on GitHub and Hacker News.",
  },
  {
    rank: 2,
    term: "Supply chain visibility software",
    category: "Logistics",
    region: "Europe",
    momentum: "+84%",
    note: "Search interest spiking after recent port disruptions.",
  },
  {
    rank: 3,
    term: "AI content moderation",
    category: "Content & Trust",
    region: "North America",
    momentum: "+71%",
    note: "Enterprise RFP volume up sharply this quarter.",
  },
  {
    rank: 4,
    term: "Headless commerce",
    category: "Retail",
    region: "APAC",
    momentum: "+63%",
    note: "Merchants migrating off monolithic storefronts.",
  },
  {
    rank: 5,
    term: "Localization for SaaS",
    category: "Developer Tools",
    region: "Global",
    momentum: "+58%",
    note: "Product-led teams expanding beyond English markets.",
  },
  {
    rank: 6,
    term: "Proptech for small landlords",
    category: "Real Estate",
    region: "North America",
    momentum: "+52%",
    note: "The underserved micro-operator segment is heating up.",
  },
  {
    rank: 7,
    term: "B2B embedded finance",
    category: "Fintech",
    region: "Europe",
    momentum: "+47%",
    note: "Marketplaces bundling payments and lending.",
  },
  {
    rank: 8,
    term: "Security observability",
    category: "Security",
    region: "Global",
    momentum: "+43%",
    note: "Buyers consolidating monitoring and threat tooling.",
  },
];

export default function TrendingPage() {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-4xl">
      <header className="text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/15 text-primary">
          <Flame aria-hidden="true" className="size-6" />
        </div>
        <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Trending now
        </h1>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
          The fastest-moving topics across markets, ranked by momentum.
        </p>
      </header>

      <ol className="mt-8 space-y-3">
        {TRENDING.map((topic) => (
          <li key={topic.term}>
            <button
              type="button"
              onClick={() =>
                router.push(
                  `/dashboard/intelligence/results?q=${encodeURIComponent(topic.term)}`,
                )
              }
              className="group flex w-full items-center gap-4 rounded-2xl border border-border bg-card p-4 text-left transition-colors hover:border-primary/40 sm:items-center"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted font-display text-sm font-semibold text-muted-foreground">
                {topic.rank}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-display text-base font-semibold tracking-tight text-foreground">
                    {topic.term}
                  </h2>
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
                    {topic.momentum}
                  </span>
                </div>
                <p className="mt-0.5 truncate text-sm text-muted-foreground">{topic.note}</p>
                <p className="mt-1 text-xs text-muted-foreground/80">
                  {topic.category} · {topic.region}
                </p>
              </div>
              <ArrowUpRight
                aria-hidden="true"
                className="size-4 shrink-0 text-muted-foreground transition-all group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary"
              />
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
