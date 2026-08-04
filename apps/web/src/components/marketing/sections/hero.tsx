import {
  Activity,
  ArrowRight,
  Boxes,
  Globe,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { AuthAwareCta } from "@/components/marketing/auth-aware-cta";
import { Button } from "@/components/ui/button";
import { signalSources } from "@/config";
import { cn } from "@/lib/utils";

const inventoryBars = [42, 58, 48, 66, 54, 72];
const demandBars = [28, 44, 40, 58, 66, 84];

function MiniBars({
  bars,
  className,
  tone = "sky",
}: {
  bars: number[];
  className?: string;
  tone?: "sky" | "outline";
}) {
  return (
    <div
      className={cn("flex items-end gap-1", className)}
      aria-hidden="true"
    >
      {bars.map((height, index) => (
        <span
          key={index}
          className={cn("w-1.5 rounded-full", tone === "sky" ? "bg-primary" : "bg-border")}
          style={{ height: `${height}%` }}
        />
      ))}
    </div>
  );
}

function ConsoleNode({
  icon: Icon,
  label,
  sub,
  tone = "default",
}: {
  icon: LucideIcon;
  label: string;
  sub: string;
  tone?: "default" | "highlight";
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-4 transition-shadow",
        tone === "highlight"
          ? "border-primary/60 bg-primary/15 shadow-lg shadow-primary/20"
          : "border-border bg-muted/40",
      )}
    >
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "flex size-8 items-center justify-center rounded-lg",
            tone === "highlight" ? "bg-primary text-primary-foreground" : "bg-card text-primary ring-1 ring-border",
          )}
        >
          <Icon aria-hidden="true" className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-semibold text-foreground">
            {label}
          </p>
          <p className="truncate text-xs text-muted-foreground">{sub}</p>
        </div>
      </div>
    </div>
  );
}

function NodeLink({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-1 self-stretch" aria-hidden="true">
      <span className="h-px flex-1 bg-border" />
      <span className="font-mono text-xs text-muted-foreground">{label}</span>
      <ArrowRight className="size-3.5 text-primary" />
    </div>
  );
}

function SignalConsole() {
  return (
    <div className="relative mx-auto w-full max-w-3xl">
      <div
        aria-hidden="true"
        className="absolute -inset-6 -z-10 rounded-3xl bg-primary/15 blur-2xl"
      />
      <div className="overflow-hidden rounded-2xl border border-border bg-card/90 shadow-2xl shadow-[#4cb6e1]/10 backdrop-blur-sm">
        <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
          <div className="flex gap-1.5" aria-hidden="true">
            <span className="size-2.5 rounded-full bg-border" />
            <span className="size-2.5 rounded-full bg-border" />
            <span className="size-2.5 rounded-full bg-border" />
          </div>
          <p className="font-mono text-xs text-muted-foreground">
            skyrict · live signal
          </p>
          <span className="flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
            <Activity aria-hidden="true" className="size-3" />
            all sources live
          </span>
        </div>
        <div className="grid gap-4 p-6 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
          <div className="grid gap-3">
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  internal · ERP
                </p>
                <MiniBars bars={inventoryBars} className="h-7" />
              </div>
              <ConsoleNode
                icon={Boxes}
                label="InventoryLevel"
                sub="inventory · sales · cash"
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                  external · market
                </p>
                <MiniBars bars={demandBars} className="h-7" tone="outline" />
              </div>
              <ConsoleNode
                icon={Globe}
                label="DemandScore"
                sub="trends · youtube · reddit"
              />
            </div>
          </div>
          <NodeLink label="feeds" />
          <div className="space-y-2 sm:mx-auto sm:w-full sm:max-w-xs">
            <div className="flex items-center justify-between gap-2">
              <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
                synthesis
              </p>
            </div>
            <ConsoleNode
              icon={Activity}
              label="MarketCategory"
              sub="cross-referenced category"
              tone="highlight"
            />
            <NodeLink label="acts" />
            <ConsoleNode
              icon={Sparkles}
              label="AgentInsight"
              sub="your next move, reasoned"
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border/70 px-6 py-3.5">
          <span className="mr-1 font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            sources
          </span>
          {signalSources.map((source) => (
            <span
              key={source}
              className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground"
            >
              {source}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="mx-auto w-full max-w-6xl px-6 pb-24 pt-16 sm:pt-24">
        <div className="mx-auto max-w-3xl text-center">
          <p className="mx-auto inline-flex items-center gap-2 rounded-full border border-primary/40 bg-primary/10 px-3 py-1 font-mono text-xs uppercase tracking-[0.18em] text-primary">
            <Activity aria-hidden="true" className="size-3.5" />
            AI Business Operating System
          </p>
          <h1 className="mt-6 font-display text-4xl font-semibold leading-tight tracking-tight text-foreground sm:text-5xl md:text-6xl">
            Plan your business on real demand, not gut feel.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            {`Skyrict pairs a deliberately scoped ERP \n inventory, sales, cash, orders \n with live signals from Google Trends, YouTube, Reddit, GitHub, and news. AI agents read both sides at once and tell you what to do next.`}
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <AuthAwareCta />
            <Button variant="outline" size="lg" asChild>
              <Link href="/#how-it-works">
                See how it works
                <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
            </Button>
          </div>
          <p className="mt-5 font-mono text-xs text-muted-foreground/80">
            Argon2id auth · email verification · MFA-ready
          </p>
        </div>
        <div className="mt-20">
          <SignalConsole />
        </div>
      </div>
    </section>
  );
}

export { Hero };
