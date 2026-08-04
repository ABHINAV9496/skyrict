import { RevealSection } from "@/components/marketing/reveal-section";
import { pillars } from "@/config";

function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20">
      <div className="mx-auto w-full max-w-6xl px-6 py-20 sm:py-28">
        <RevealSection>
          <div className="mx-auto max-w-2xl text-center">
            <p className="font-mono text-xs uppercase tracking-[0.2em] text-primary">
              How it works
            </p>
            <h2 className="mt-4 font-display text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
              Three parts. One operating picture.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-muted-foreground">
              Skyrict is deliberately scoped. It tracks the slice of your
              operations that matters, listens to the market continuously, and
              puts agents on top of the synthesis.
            </p>
          </div>
        </RevealSection>
        <div className="mt-16 grid gap-6 md:grid-cols-3">
          {pillars.map((pillar, index) => (
            <RevealSection key={pillar.index} delay={index * 120}>
              <article className="group relative h-full rounded-2xl border border-border bg-card p-7 transition-shadow hover:shadow-lg hover:shadow-primary/10">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm text-primary">
                    {pillar.index}
                  </span>
                  <span
                    aria-hidden="true"
                    className="h-px flex-1 bg-border transition-colors group-hover:bg-primary/50"
                  />
                </div>
                <h3 className="mt-5 font-display text-xl font-semibold text-foreground">
                  {pillar.name}
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  {pillar.description}
                </p>
              </article>
            </RevealSection>
          ))}
        </div>
      </div>
    </section>
  );
}

export { HowItWorks };
