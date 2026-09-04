import { Boxes, Globe, Sparkles } from "lucide-react";

import { Logo } from "@/components/brand/logo";

const authValueProps = [
  {
    icon: Boxes,
    title: "One source of internal truth",
    body: "Inventory, sales, cash, and orders - a deliberately scoped ERP slice. Not a bloated replacement; the ~20% that 80% of SMBs actually use.",
  },
  {
    icon: Globe,
    title: "External market truth",
    body: "Demand signals pulled continuously from Google Trends, YouTube, Reddit, GitHub, and news.",
  },
  {
    icon: Sparkles,
    title: "Agents that act",
    body: "AI that reasons across both sides at once - and answers what no single tool can.",
  },
] as const;

function AuthBrandPanel() {
  return (
    <aside className="relative hidden overflow-hidden bg-[#0a2f3e] p-12 text-[#f4fafd] lg:flex lg:h-full lg:flex-col lg:justify-between">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(60% 50% at 15% 10%, rgba(135,206,235,0.18), transparent 70%), radial-gradient(50% 40% at 90% 100%, rgba(76,182,225,0.12), transparent 70%)",
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 opacity-[0.07]"
        style={{
          backgroundImage:
            "radial-gradient(rgba(244,250,253,0.9) 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }}
      />

      <div className="relative flex items-center justify-between">
        <Logo className="text-[#f4fafd]" />
        <span className="font-mono text-xs uppercase tracking-[0.2em] text-[#aedef1]">
          Business OS
        </span>
      </div>

      <div className="relative max-w-md space-y-8">
        <p className="font-mono text-xs uppercase tracking-[0.2em] text-[#87ceeb]">
          Internal truth × external truth
        </p>
        <h2 className="font-display text-3xl font-semibold leading-snug text-[#f4fafd]">
          Your operations meet the market - in one plane.
        </h2>
        <ul className="space-y-5">
          {authValueProps.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex items-start gap-3.5">
              <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-[#87ceeb]/15 text-[#aedef1]">
                <Icon aria-hidden="true" className="size-4.5" />
              </span>
              <div className="space-y-0.5">
                <p className="text-sm font-semibold text-[#f4fafd]">
                  {title}
                </p>
                <p className="text-sm leading-relaxed text-[#aedef1]/90">
                  {body}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="relative flex items-center gap-3">
        <span className="relative flex size-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#87ceeb] opacity-60" />
          <span className="relative inline-flex size-2.5 rounded-full bg-[#87ceeb]" />
        </span>
        <p className="font-mono text-xs text-[#aedef1]/80">
          inventory · market · agents - online
        </p>
      </div>
    </aside>
  );
}

export { AuthBrandPanel };
