import {
  ArrowRight,
  Boxes,
  Globe,
  Lightbulb,
  type LucideIcon,
} from "lucide-react";

import { AiGlyph } from "@/components/brand/logo";
import { RevealSection } from "@/components/marketing/reveal-section";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const internalSignals = [
  "Inventory levels",
  "Sales velocity",
  "Cash on hand",
  "Open orders",
];

const marketSignals = [
  "Search demand",
  "Community buzz",
  "Competitor moves",
  "News sentiment",
];

const agentMoves = [
  `Restock size M \n demand up 34%`,
  `Raise price on line X \n stock is thin`,
  `Enter category Y \n signal rising`,
];

function TruthCard({
  icon: Icon,
  tone,
  eyebrow,
  title,
  signals,
}: {
  icon: LucideIcon;
  tone: "internal" | "market";
  eyebrow: string;
  title: string;
  signals: string[];
}) {
  return (
    <div className="h-full rounded-2xl border border-border bg-card p-6">
      <div className="flex items-center gap-2.5">
        <span
          className={cn(
            "flex size-9 items-center justify-center rounded-lg",
            tone === "internal" ? "bg-muted text-primary ring-1 ring-border" : "bg-primary/15 text-primary",
          )}
        >
          <Icon aria-hidden="true" className="size-4.5" />
        </span>
        <div>
          <p className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground">
            {eyebrow}
          </p>
          <p className="font-display text-lg font-semibold text-foreground">
            {title}
          </p>
        </div>
      </div>
      <ul className="mt-5 space-y-2.5">
        {signals.map((signal) => (
          <li
            key={signal}
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <span
              className="size-1.5 rounded-full"
              aria-hidden="true"
              style={{ backgroundColor: tone === "internal" ? "#87ceeb" : "#4cb6e1" }}
            />
            {signal}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Bridge() {
  return (
    <section id="bridge" className="scroll-mt-20">
      <div className="mx-auto w-full max-w-6xl px-6 py-20 sm:py-28">
        <RevealSection>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
              The bridge
            </p>
            <h2 className="mt-4 font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              One decision. Two truths. Zero guessing.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              Your ERP tells you what&apos;s happening inside. The market tells
              you what&apos;s happening outside. Agents sit on the bridge and
              turn both into a concrete next move.
            </p>
          </div>
        </RevealSection>
        <div className="mt-16 grid items-stretch gap-4 lg:grid-cols-[1fr_auto_1.2fr_auto_1fr]">
          <RevealSection>
            <TruthCard
              icon={Boxes}
              tone="internal"
              eyebrow="Internal truth"
              title="Your operations"
              signals={internalSignals}
            />
          </RevealSection>
          <RevealSection className="hidden lg:flex" delay={120}>
            <ArrowRight
              aria-hidden="true"
              className="mx-auto h-full w-8 self-center text-primary/70"
            />
          </RevealSection>
          <RevealSection delay={180}>
            <div className="flex h-full flex-col rounded-2xl border border-primary/50 bg-primary/10 p-6 shadow-lg shadow-primary/15">
              <div className="flex items-center gap-2.5">
                <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <AiGlyph aria-hidden="true" className="size-4.5" />
                </span>
                <div>
                  <p className="font-mono text-[11px] uppercase tracking-wider text-primary">
                    The agent layer
                  </p>
                  <p className="font-display text-lg font-semibold text-foreground">
                    What should I do next?
                  </p>
                </div>
              </div>
              <div className="mt-5 flex flex-1 flex-col justify-center gap-2.5">
                {agentMoves.map((move) => (
                  <div
                    key={move}
                    className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-sm text-foreground"
                  >
                    <Lightbulb
                      aria-hidden="true"
                      className="size-4 shrink-0 text-primary"
                    />
                    {move}
                  </div>
                ))}
              </div>
              <div className="mt-5">
                <Badge className="bg-primary text-primary-foreground">
                  Internal + external, at once
                </Badge>
              </div>
            </div>
          </RevealSection>
          <RevealSection className="hidden lg:flex" delay={240}>
            <ArrowRight
              aria-hidden="true"
              className="mx-auto h-full w-8 -scale-x-100 self-center text-primary/70"
            />
          </RevealSection>
          <RevealSection delay={120}>
            <TruthCard
              icon={Globe}
              tone="market"
              eyebrow="External truth"
              title="The market"
              signals={marketSignals}
            />
          </RevealSection>
        </div>
      </div>
    </section>
  );
}

export { Bridge };
