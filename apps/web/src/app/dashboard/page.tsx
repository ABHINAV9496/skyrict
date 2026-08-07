import Link from "next/link";
import { Bot, Boxes, Sparkles } from "lucide-react";

const sections = [
  {
    href: "/agents",
    title: "AI Agents",
    description: "Autonomous intelligence agents",
    icon: Bot,
  },
  {
    href: "/erp",
    title: "ERP",
    description: "Enterprise resource planning",
    icon: Boxes,
  },
  {
    href: "/intelligence",
    title: "Intelligence",
    description: "Analytics and insights",
    icon: Sparkles,
  },
];

export default function DashboardHomePage() {
  return (
    <main className="space-y-6">
      <div className="space-y-2">
        <h1 className="font-display text-2xl font-semibold text-foreground">
          Welcome to Skyrict
        </h1>
        <p className="text-sm text-muted-foreground">
          Your workspace is ready. Pick a module to get started.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {sections.map((section) => (
          <Link
            key={section.href}
            href={section.href}
            className="group rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/40 hover:bg-muted/40"
          >
            <section.icon
              aria-hidden="true"
              className="size-5 text-primary"
            />
            <p className="mt-3 text-sm font-semibold text-foreground">
              {section.title}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {section.description}
            </p>
          </Link>
        ))}
      </div>
    </main>
  );
}
