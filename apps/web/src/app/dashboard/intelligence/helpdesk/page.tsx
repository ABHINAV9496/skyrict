import { CircleHelp } from "lucide-react";

const FAQS = [
  {
    question: "Where does Skyrict GMIE get its data?",
    answer:
      "Signals are gathered across news, social, code, and trend sources, then cross-referenced so each finding lists its confidence and timeframe.",
  },
  {
    question: "How do I scope research to a specific country or region?",
    answer:
      "Use the country selector in the top-right of the navbar. It persists for your session and the region is factored into searches and signals.",
  },
  {
    question: "Why do some results have low confidence?",
    answer:
      "Confidence reflects how many independent sources agree. Low-confidence items are still surfaced because early signals often matter most.",
  },
  {
    question: "Can I export or save research?",
    answer:
      "Saving and exporting are coming soon. For now, each research pass can be re-run from Home, Explore, or Trending with a single click.",
  },
];

export default function HelpdeskPage() {
  return (
    <div className="mx-auto max-w-3xl">
      <header className="text-center">
        <div className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-primary/15 text-primary">
          <CircleHelp aria-hidden="true" className="size-6" />
        </div>
        <h1 className="mt-4 font-display text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          Helpdesk
        </h1>
        <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-muted-foreground">
          Answers to the questions we hear most about Skyrict GMIE.
        </p>
      </header>

      <div className="mt-8 space-y-3">
        {FAQS.map((faq) => (
          <details
            key={faq.question}
            className="group rounded-2xl border border-border bg-card p-5 open:border-primary/40"
          >
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-left font-display text-base font-semibold tracking-tight text-foreground">
              {faq.question}
              <span
                aria-hidden="true"
                className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground transition-transform group-open:rotate-45"
              >
                +
              </span>
            </summary>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{faq.answer}</p>
          </details>
        ))}
      </div>
    </div>
  );
}
