"use client";

import { useRouter } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  Database,
  Globe,
  Radio,
  Zap,
} from "lucide-react";

const KPI_STATS = [
  { label: "Markets tracked", value: "12", icon: Globe },
  { label: "Live signals", value: "1,204", icon: Radio },
  { label: "Sources", value: "4", hint: "News · Social · Code · Trends", icon: Database },
  { label: "Data freshness", value: "Live", icon: Activity },
];

interface RegionCard {
  name: string;
  growth: string;
  note: string;
  query: string;
}

const REGIONS: RegionCard[] = [
  {
    name: "North America",
    growth: "+9.2% YoY",
    note: "Enterprise and AI infrastructure demand leads.",
    query: "market opportunities in North America",
  },
  {
    name: "Europe",
    growth: "+6.8% YoY",
    note: "Compliance-driven software spend rising.",
    query: "market opportunities in Europe",
  },
  {
    name: "APAC",
    growth: "+14.1% YoY",
    note: "Fastest-growing region for SaaS adoption.",
    query: "market opportunities in APAC",
  },
  {
    name: "Latin America",
    growth: "+11.5% YoY",
    note: "Embedded payments and fintech expanding.",
    query: "market opportunities in Latin America",
  },
  {
    name: "Middle East & Africa",
    growth: "+8.9% YoY",
    note: "Fintech and logistics picking up speed.",
    query: "market opportunities in the Middle East and Africa",
  },
];

interface MarketSignal {
  label: string;
  category: string;
  region: string;
  momentum: string;
}

const SIGNALS: MarketSignal[] = [
  {
    label: "Pricing pressure in analytics tools intensifies",
    category: "Pricing",
    region: "North America",
    momentum: "+23%",
  },
  {
    label: "Localization demand outpaces supply",
    category: "Localization",
    region: "Global",
    momentum: "+18%",
  },
  {
    label: "Agentic AI consolidates into platform bets",
    category: "AI & Infrastructure",
    region: "Global",
    momentum: "+31%",
  },
];

export default function MarketPage() {
  const router = useRouter();

  return (
    <div className="mx-auto max-w-4xl space-y-10">
      <header className="text-center">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Market overview
        </h1>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
          A live read on regions, demand, and the signals moving the market
          right now.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {KPI_STATS.map((stat) => {
          const Icon = stat.icon;
          return (
            <div key={stat.label} className="rounded-2xl border border-border bg-card p-4">
              <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon aria-hidden="true" className="size-4" />
              </div>
              <p className="mt-3 font-display text-2xl font-semibold tracking-tight text-foreground">
                {stat.value}
              </p>
              <p className="text-sm text-muted-foreground">{stat.label}</p>
              {stat.hint ? <p className="mt-0.5 text-xs text-muted-foreground/80">{stat.hint}</p> : null}
            </div>
          );
        })}
      </div>

      <section>
        <div className="flex items-center gap-2">
          <Globe aria-hidden="true" className="size-4 text-primary" />
          <h2 className="font-display text-base font-semibold tracking-tight text-foreground">
            Regional markets
          </h2>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {REGIONS.map((region) => (
            <button
              key={region.name}
              type="button"
              onClick={() =>
                router.push(
                  `/dashboard/intelligence/results?q=${encodeURIComponent(region.query)}`,
                )
              }
              className="group rounded-2xl border border-border bg-card p-5 text-left transition-colors hover:border-primary/40"
            >
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-display text-base font-semibold tracking-tight text-foreground">
                  {region.name}
                </h3>
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
                  {region.growth}
                </span>
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{region.note}</p>
              <p className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-primary">
                Research region
                <ArrowUpRight
                  aria-hidden="true"
                  className="size-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
                />
              </p>
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="flex items-center gap-2">
          <Zap aria-hidden="true" className="size-4 text-primary" />
          <h2 className="font-display text-base font-semibold tracking-tight text-foreground">
            Key signals
          </h2>
        </div>
        <ul className="mt-4 space-y-3">
          {SIGNALS.map((signal) => (
            <li
              key={signal.label}
              className="rounded-2xl border border-border bg-card p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-foreground">{signal.label}</p>
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-400">
                  {signal.momentum}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {signal.category} · {signal.region}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
