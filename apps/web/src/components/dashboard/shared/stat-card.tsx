import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: string;
  hint?: string;
  /** When set, the whole card becomes a link. */
  href?: string;
}

/** A compact KPI card: label, value, and an optional note with an icon tile. */
export function StatCard({ icon: Icon, label, value, hint, href }: StatCardProps) {
  const cardClass = cn(
    "block rounded-xl border border-border bg-card p-5",
    href && "transition-colors hover:border-primary/40 hover:bg-muted/40",
  );

  const content = (
    <>
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
          {label}
        </p>
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon aria-hidden="true" className="size-4" />
        </span>
      </div>
      <p className="mt-2 font-display text-2xl font-semibold tracking-tight text-foreground">
        {value}
      </p>
      {hint ? <p className="mt-1 text-sm text-muted-foreground">{hint}</p> : null}
    </>
  );

  if (href) {
    return (
      <Link href={href} className={cardClass}>
        {content}
      </Link>
    );
  }

  return <div className={cardClass}>{content}</div>;
}
